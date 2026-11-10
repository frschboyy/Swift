//! Spike: the motions of `../card_origin.py`, drawn by a webview as Swift's overlay would.
//!
//! One transparent, click-through window covers the main monitor and never moves. The card
//! is a div inside it, animated by the webview. For the push, the webview says when its
//! animation began and Rust moves the real window from that moment, on the same curve.
//!
//! A card that came from a window belongs to it, without chasing it:
//! - you drag the window: the card lets go (lifts and dims), then re-settles when you drop it;
//! - another window takes the front: the card folds away where it is, and comes back when
//!   its window does;
//! - a card waiting on an answer never hides itself: it travels home to Swift's place (a
//!   stand-in spot above the taskbar) and stays visible there.
//!
//! Ctrl+Alt+R draws on top of the app's own UI: a ring around whichever control has focus,
//! tied by a line to a card. It only reads where the control is (UI Automation), never its
//! text, and changes nothing in the app. One loop owns the ring: it hides the moment the
//! control moves or its window leaves the front, and returns when the control is still.
//!
//!     cargo run                 Ctrl+Alt+W card from the window, A the same but waiting on an
//!                               answer, T taskbar, P push, R ring, Q quit (same key = back)
//!     cargo run -- --selftest   hands-off; moves nothing of yours

use std::ffi::c_void;
use std::sync::atomic::{AtomicIsize, AtomicU32, Ordering};
use std::sync::{mpsc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tauri::{AppHandle, Manager, PhysicalSize, State};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED};
use windows::Win32::UI::Accessibility::{CUIAutomation, IUIAutomation, IUIAutomationElement};

/// How long a control must hold still before its ring returns. Hiding is instant; coming
/// back at once made the ring blink through every pause in a scroll.
const STILL_TICKS: u32 = 8; // of 50 ms

/// What kind of thing the app says has focus. The ring is as big as this is.
fn kind_name(id: i32) -> &'static str {
    match id {
        50000 => "a button",
        50002 => "a check box",
        50003 => "a combo box",
        50004 => "a text box",
        50005 => "a link",
        50007 => "a list item",
        50008 => "a list",
        50011 => "a menu item",
        50019 => "a tab",
        50024 => "a tree item",
        50030 => "a whole document",
        50032 => "a whole window",
        50033 => "a whole pane",
        _ => "another kind of control",
    }
}

type Hwnd = *mut c_void;
type WinEventProc = unsafe extern "system" fn(Hwnd, u32, Hwnd, i32, i32, u32, u32);

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct Rect {
    left: i32,
    top: i32,
    right: i32,
    bottom: i32,
}

// Declared by hand so the spike adds no crate or feature.
#[link(name = "user32")]
extern "system" {
    fn GetForegroundWindow() -> Hwnd;
    fn GetWindowRect(h: Hwnd, r: *mut Rect) -> i32;
    fn SetWindowPos(h: Hwnd, after: Hwnd, x: i32, y: i32, cx: i32, cy: i32, flags: u32) -> i32;
    fn IsZoomed(h: Hwnd) -> i32;
    fn FindWindowW(class: *const u16, title: *const u16) -> Hwnd;
    fn FindWindowExW(parent: Hwnd, after: Hwnd, class: *const u16, title: *const u16) -> Hwnd;
    fn NotifyWinEvent(event: u32, h: Hwnd, object: i32, child: i32);
    fn GetDesktopWindow() -> Hwnd;
    fn SetWinEventHook(min: u32, max: u32, module: Hwnd, f: WinEventProc, pid: u32, tid: u32, flags: u32) -> Hwnd;
}
#[link(name = "dwmapi")]
extern "system" {
    fn DwmFlush() -> i32;
    fn DwmGetWindowAttribute(h: Hwnd, attr: u32, out: *mut c_void, size: u32) -> i32;
}

const CARD_W: i32 = 320;
const GROW_MS: u64 = 260;
const APPROACH_MS: u64 = 120; // the card closes the gap, then card and window travel together
const PUSH_MS: u64 = 220;
const MOVE_ONLY: u32 = 0x1 | 0x4 | 0x10; // no size, no z-order, no activate
const FOREGROUND: u32 = 0x0003; // EVENT_SYSTEM_FOREGROUND
const MOVE_START: u32 = 0x000A; // EVENT_SYSTEM_MOVESIZESTART
const MOVE_END: u32 = 0x000B; // EVENT_SYSTEM_MOVESIZEEND

static APP: OnceLock<AppHandle> = OnceLock::new(); // the event hook's callback takes no context
static TEST_FG: AtomicIsize = AtomicIsize::new(0); // selftest: stands in for the active window

/// A real window's move, waiting for the webview to say its animation began.
#[derive(Clone, Copy)]
struct Move {
    hwnd: isize,
    from: i32,
    to: i32,
    y: i32,
    delay_ms: u64,
}

struct Open {
    kind: &'static str,
    hwnd: isize, // the window the card came from; 0 if it didn't come from one
    dst: [i32; 4],
    waiting: bool,
    away: bool,   // at home, because another window has the front
    lifted: bool, // let go, because its window is being dragged
    pushed: Option<(isize, i32, i32)>, // the window made to give room, and where it was
}

/// Asked of the thread that talks to UI Automation.
enum Uia {
    Ring,
    Read(mpsc::Sender<Option<f64>>), // selftest: how long finding the focused control took
}

struct St {
    origin: (i32, i32),
    size: (i32, i32),
    uia: Mutex<mpsc::Sender<Uia>>,
    open: Mutex<Option<Open>>,
    pending: Mutex<Option<Move>>,
    started: AtomicU32,
    seen: Mutex<Option<[f64; 5]>>,
}

impl St {
    /// A screen rectangle as the page wants it: device pixels from the canvas's corner.
    fn arr(&self, r: [i32; 4]) -> String {
        format!("[{},{},{},{}]", r[0] - self.origin.0, r[1] - self.origin.1, r[2], r[3])
    }

    fn go_js(&self, kind: &str, waiting: bool, src: [i32; 4], dst: [i32; 4]) -> String {
        format!(
            "go({{kind:'{kind}',waiting:{waiting},src:{},dst:{},grow:{GROW_MS},approach:{APPROACH_MS},push:{PUSH_MS}}},{})",
            self.arr(src),
            self.arr(dst),
            now_ms()
        )
    }
}

fn now_ms() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64() * 1000.0
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain([0]).collect()
}

/// The rectangle you actually see (GetWindowRect includes invisible resize borders).
fn frame(h: Hwnd) -> Rect {
    let mut r = Rect::default();
    unsafe {
        if DwmGetWindowAttribute(h, 9, &mut r as *mut _ as *mut c_void, 16) != 0 {
            GetWindowRect(h, &mut r);
        }
    }
    r
}

fn taskbar() -> Hwnd {
    unsafe { FindWindowW(wide("Shell_TrayWnd").as_ptr(), std::ptr::null()) }
}

fn tray() -> Rect {
    // shortcut: the whole notification area, not one icon; a single icon's rect needs UI Automation
    let mut r = Rect::default();
    unsafe {
        let bar = taskbar();
        let area = FindWindowExW(bar, std::ptr::null_mut(), wide("TrayNotifyWnd").as_ptr(), std::ptr::null());
        GetWindowRect(if area.is_null() { bar } else { area }, &mut r);
    }
    r
}

/// Swift's own place, where a card goes when its window isn't in front.
/// shortcut: a fixed spot above the taskbar; in Swift this is the Deck's corner.
fn home() -> [i32; 4] {
    let r = tray();
    [(r.right - 352).max(0), r.top - 172, 340, 160]
}

/// Where a window's card starts (a sliver of its title bar) and where it rests.
fn window_rects(f: Rect) -> ([i32; 4], [i32; 4]) {
    let cx = (f.left + f.right) / 2;
    ([cx - 30, f.top, 60, 6], [cx - 180, f.top + 44, 360, 180])
}

/// Where a window's card rests: over the window, or for the push, in the strip beside it.
fn rest(kind: &str, f: Rect) -> [i32; 4] {
    if kind == "push" {
        [f.left - CARD_W, f.top, CARD_W, f.bottom - f.top]
    } else {
        window_rects(f).1
    }
}

fn run_move(m: Move) {
    thread::sleep(Duration::from_millis(m.delay_ms));
    let t0 = Instant::now();
    loop {
        unsafe { DwmFlush() }; // one step per composed frame
        let u = (t0.elapsed().as_secs_f64() * 1000.0 / PUSH_MS as f64).min(1.0);
        let x = m.from + ((m.to - m.from) as f64 * (1.0 - (1.0 - u).powi(2))).round() as i32;
        if unsafe { SetWindowPos(m.hwnd as Hwnd, std::ptr::null_mut(), x, m.y, 0, 0, MOVE_ONLY) } == 0 {
            println!("can't move that window (elevated app?)");
            return;
        }
        if u >= 1.0 {
            return;
        }
    }
}

#[tauri::command]
fn started(sent: f64, st: State<St>) {
    println!("webview began {:.0} ms after it was told", now_ms() - sent);
    st.started.fetch_add(1, Ordering::SeqCst);
    if let Some(m) = st.pending.lock().unwrap().take() {
        thread::spawn(move || run_move(m));
    }
}

#[tauri::command]
fn probe(v: [f64; 5], st: State<St>) {
    *st.seen.lock().unwrap() = Some(v);
}

fn toggle(app: &AppHandle, kind: &'static str) {
    let st = app.state::<St>();
    let win = app.get_webview_window("canvas").unwrap();
    let mut open = st.open.lock().unwrap();
    if let Some(o) = open.as_ref() {
        if o.kind != kind {
            println!("put the open card back first (same key again)");
            return;
        }
        let mut js = format!("go(null,{})", now_ms());
        match o.pushed {
            Some((hwnd, x0, y0)) => {
                let m = Move { hwnd, from: x0 + CARD_W, to: x0, y: y0, delay_ms: 0 };
                if o.away {
                    // The card is hidden at home: give the room back without showing it again.
                    thread::spawn(move || run_move(m));
                    js.clear();
                } else {
                    *st.pending.lock().unwrap() = Some(m);
                }
            }
            // The owner dragged the pushed window: it's theirs to place, so only the card leaves.
            None if o.kind == "push" => js = format!("fly({},0,{PUSH_MS})", st.arr(o.dst)),
            None => {}
        }
        *open = None;
        if !js.is_empty() {
            let _ = win.eval(&js);
        }
        return;
    }

    // Read where the source is, once.
    let (src, dst, hwnd, pushed) = if kind == "tray" {
        let r = tray();
        let (cx, cy) = ((r.left + r.right) / 2, (r.top + r.bottom) / 2);
        ([cx - 12, cy - 12, 24, 24], home(), 0, None)
    } else {
        let test = TEST_FG.load(Ordering::SeqCst);
        let h = if test != 0 { test as Hwnd } else { unsafe { GetForegroundWindow() } };
        if h.is_null() {
            println!("no active window");
            return;
        }
        let f = frame(h);
        if kind != "push" {
            let (src, dst) = window_rects(f);
            (src, dst, h as isize, None)
        } else {
            if unsafe { IsZoomed(h) } != 0 {
                println!("a maximised window has nowhere to move to");
                return;
            }
            let mut r = Rect::default();
            unsafe { GetWindowRect(h, &mut r) };
            *st.pending.lock().unwrap() =
                Some(Move { hwnd: h as isize, from: r.left, to: r.left + CARD_W, y: r.top, delay_ms: APPROACH_MS });
            ([0; 4], [f.left, f.top, CARD_W, f.bottom - f.top], h as isize, Some((h as isize, r.left, r.top)))
        }
    };
    let waiting = kind == "ask";
    *open = Some(Open { kind, hwnd, dst, waiting, away: false, lifted: false, pushed });
    let _ = win.eval(&st.go_js(kind, waiting, src, dst));
}

/// The desktop changed: keep a window's card belonging to its window, without chasing it.
fn desktop_event(app: &AppHandle, event: u32, hwnd: isize) {
    let st = app.state::<St>();
    let mut open = st.open.lock().unwrap();
    // Say what was noticed and done: three rare events, and the owner can't see inside.
    let name = match event {
        FOREGROUND => "front",
        MOVE_START => "drag start",
        MOVE_END => "drag end",
        _ => return,
    };
    let Some(o) = open.as_mut() else {
        println!("{name}: no card open");
        return;
    };
    if o.kind == "ring" {
        return; // the ring's own loop watches its control
    }
    if o.hwnd == 0 {
        println!("{name}: the open card ({}) belongs to no window, so it stays", o.kind);
        return;
    }
    let mine = hwnd == o.hwnd;
    let whose = if mine { "the card's window" } else { "another window" };
    let (did, js) = match event {
        MOVE_START if mine && !o.away => {
            o.lifted = true;
            let d = o.dst;
            ("lets go", format!("fly({},0.5,120)", st.arr([d[0], d[1] - 8, d[2], d[3]])))
        }
        MOVE_END if mine && o.lifted => {
            o.lifted = false;
            o.dst = rest(o.kind, frame(hwnd as Hwnd)); // read once, where it was dropped
            o.pushed = None; // a window the owner dragged is theirs to place: never put it back
            ("re-settles", format!("fly({},1,{GROW_MS})", st.arr(o.dst)))
        }
        FOREGROUND if !mine && !o.away => {
            o.away = true;
            o.lifted = false;
            if o.waiting {
                // A question stays on screen: a plain "yes" only counts while it's visible.
                ("goes home", format!("fly({},1,{GROW_MS})", st.arr(home())))
            } else {
                // A card that only hides folds away where it is. Flying it home while it
                // faded read as a flicker on the owner's screen.
                let d = o.dst;
                let into = if o.kind == "push" {
                    [d[0] - CARD_W / 2, d[1], d[2], d[3]] // back out the way it came
                } else {
                    window_rects(frame(o.hwnd as Hwnd)).0 // into its window's title bar
                };
                ("folds away", format!("fly({},0,180)", st.arr(into)))
            }
        }
        FOREGROUND if mine && o.away => {
            o.away = false;
            let f = frame(hwnd as Hwnd);
            o.dst = rest(o.kind, f);
            let js = if o.waiting || o.kind == "push" {
                format!("fly({},1,{GROW_MS})", st.arr(o.dst)) // travel back from home
            } else {
                st.go_js(o.kind, false, window_rects(f).0, o.dst) // it was hidden: unfold from the window again
            };
            ("comes back", js)
        }
        _ => {
            println!("{name}, {whose}: nothing to do");
            return;
        }
    };
    println!("{name}, {whose}: the card {did}");
    let _ = app.get_webview_window("canvas").unwrap().eval(&js);
}

/// Where a mark's card goes: below and right of its control, or the other side if that's off screen.
fn card_for(r: [i32; 4], st: &St) -> [i32; 4] {
    let (w, h) = (260, 96);
    let (right, bottom) = (st.origin.0 + st.size.0, st.origin.1 + st.size.1 - 60);
    let x = if r[0] + r[2] + 48 + w <= right { r[0] + r[2] + 48 } else { r[0] - 48 - w };
    let y = if r[1] + r[3] + 36 + h <= bottom { r[1] + r[3] + 36 } else { r[1] - 36 - h };
    [x.max(st.origin.0), y.max(st.origin.1), w, h]
}

fn ring_key(app: &AppHandle) {
    let st = app.state::<St>();
    let mut open = st.open.lock().unwrap();
    match open.as_ref() {
        Some(o) if o.kind == "ring" => *open = None, // its loop sees this and takes the ring away
        Some(_) => println!("put the open card back first (same key again)"),
        None => {
            let _ = st.uia.lock().unwrap().send(Uia::Ring);
        }
    }
}

/// UI Automation lives on its own thread: it can be slow, and must never stall the window.
fn uia_thread(app: AppHandle, rx: mpsc::Receiver<Uia>) {
    let uia: IUIAutomation = unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        match CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) {
            Ok(u) => u,
            Err(e) => return println!("UI Automation isn't available, so no rings: {e}"),
        }
    };
    // Only where the control is. Never its name or text.
    let place = |el: &IUIAutomationElement| {
        unsafe { el.CurrentBoundingRectangle() }
            .ok()
            .filter(|r| r.right > r.left && r.bottom > r.top)
            .map(|r| [r.left, r.top, r.right - r.left, r.bottom - r.top])
    };
    for req in rx {
        let t = Instant::now();
        let el = unsafe { uia.GetFocusedElement() }.ok();
        let found = el.as_ref().and_then(&place);
        let ms = t.elapsed().as_secs_f64() * 1000.0;
        match (req, el, found) {
            (Uia::Read(tx), _, found) => {
                let _ = tx.send(found.map(|_| ms));
            }
            (Uia::Ring, Some(el), Some(first)) => {
                let kind = unsafe { el.CurrentControlType() }.map_or(0, |k| k.0);
                println!("found the focused control ({}) in {ms:.0} ms", kind_name(kind));
                watch_ring(&app, first, || place(&el));
            }
            _ => println!("nothing has focus that Windows can describe"),
        }
    }
}

/// The one owner of the ring: show it while its control is still and its window is in
/// front, hide it the moment either changes, and leave when the key is pressed again.
fn watch_ring(app: &AppHandle, first: [i32; 4], place: impl Fn() -> Option<[i32; 4]>) {
    let st = app.state::<St>();
    let win = app.get_webview_window("canvas").unwrap();
    let hwnd = unsafe { GetForegroundWindow() } as isize;
    {
        let mut open = st.open.lock().unwrap();
        if open.is_some() {
            return println!("put the open card back first (same key again)");
        }
        *open = Some(Open { kind: "ring", hwnd, dst: [0; 4], waiting: false, away: false, lifted: false, pushed: None });
    }
    let (mut prev, mut shown, mut reads, mut still) = (Some(first), None, Vec::new(), STILL_TICKS);
    while matches!(st.open.lock().unwrap().as_ref(), Some(o) if o.kind == "ring") {
        let t = Instant::now();
        let now = place();
        reads.push(t.elapsed().as_secs_f64() * 1000.0);
        if now.is_none() {
            println!("the control is gone: the ring leaves");
            *st.open.lock().unwrap() = None;
            break;
        }
        let front = unsafe { GetForegroundWindow() } as isize == hwnd;
        still = if now == prev { still + 1 } else { 0 };
        let want = if front && still >= STILL_TICKS { now } else { None };
        if want != shown {
            println!("ring: {}", match (want, front) {
                (Some(_), _) => "shown on its control",
                (None, true) => "hidden, the control is moving",
                (None, false) => "hidden, its window isn't in front",
            });
            let _ = win.eval(&match want {
                Some(r) => format!("mark({},{})", st.arr(r), st.arr(card_for(r, &st))),
                None => "unmark()".into(),
            });
            shown = want;
        }
        prev = now;
        thread::sleep(Duration::from_millis(50));
    }
    if shown.is_some() {
        let _ = win.eval("unmark()");
    }
    reads.sort_by(|a, b| a.total_cmp(b));
    println!(
        "ring: asked where the control was {} times, median {:.1} ms, slowest {:.1} ms",
        reads.len(),
        reads[reads.len() / 2],
        reads[reads.len() - 1]
    );
}

unsafe extern "system" fn on_win_event(_hook: Hwnd, event: u32, hwnd: Hwnd, id_object: i32, _child: i32, _thread: u32, _ms: u32) {
    if id_object == 0 && !hwnd.is_null() {
        // 0 = the window itself
        if let Some(app) = APP.get() {
            desktop_event(app, event, hwnd as isize);
        }
    }
}

fn quit(app: &AppHandle) {
    // Never leave the owner's window where the spike put it.
    if let Some(Open { pushed: Some((hwnd, x0, y0)), .. }) = app.state::<St>().open.lock().unwrap().take() {
        unsafe { SetWindowPos(hwnd as Hwnd, std::ptr::null_mut(), x0, y0, 0, 0, MOVE_ONLY) };
    }
    app.exit(0);
}

/// Selftest: where the page says the card is (device pixels from the canvas's corner) and its opacity.
fn look(app: &AppHandle) -> [f64; 5] {
    thread::sleep(Duration::from_millis(450)); // let the motion finish
    let st = app.state::<St>();
    *st.seen.lock().unwrap() = None;
    let _ = app.get_webview_window("canvas").unwrap().eval("probe()");
    for _ in 0..100 {
        if let Some(v) = *st.seen.lock().unwrap() {
            return v;
        }
        thread::sleep(Duration::from_millis(10));
    }
    [f64::NAN; 5]
}

fn selftest(app: AppHandle) {
    thread::sleep(Duration::from_secs(3)); // let the page load
    let st = app.state::<St>();
    let failed = std::cell::Cell::new(false);
    let report = |what: &str, ok: bool| {
        println!("{} {what}", if ok { "ok  " } else { "FAIL" });
        failed.set(failed.get() | !ok);
    };
    let check = |what: &str, v: [f64; 5], at: Option<[i32; 4]>, opacity: f64| {
        let o = [st.origin.0, st.origin.1, 0, 0];
        report(what, (v[4] - opacity).abs() < 0.05
            && at.map_or(true, |r| (0..4).all(|i| (v[i] - (r[i] - o[i]) as f64).abs() <= 2.0)));
    };

    toggle(&app, "tray");
    check("the taskbar card opens at home", look(&app), Some(home()), 1.0);
    toggle(&app, "tray");
    check("and goes back", look(&app), None, 0.0);

    // The taskbar stands in for the owner's window: it's always there and nothing moves it.
    let win = taskbar() as isize;
    let other = unsafe { GetDesktopWindow() } as isize;
    // Raised as Windows would raise them, so they arrive through the real hook.
    let desktop_event = |_: &AppHandle, event: u32, h: isize| unsafe { NotifyWinEvent(event, h as Hwnd, 0, 0) };
    TEST_FG.store(win, Ordering::SeqCst);
    let dst = window_rects(frame(win as Hwnd)).1;

    toggle(&app, "ask");
    check("a waiting card opens on its window", look(&app), Some(dst), 1.0);
    desktop_event(&app, FOREGROUND, other);
    check("another window in front: it goes home and stays visible", look(&app), Some(home()), 1.0);
    desktop_event(&app, FOREGROUND, win);
    check("its window returns: it travels back", look(&app), Some(dst), 1.0);
    desktop_event(&app, MOVE_START, win);
    check("its window is dragged: it lets go", look(&app), None, 0.5);
    desktop_event(&app, MOVE_END, win);
    check("the window is dropped: it re-settles", look(&app), Some(dst), 1.0);
    toggle(&app, "ask");
    check("and goes back", look(&app), None, 0.0);

    toggle(&app, "window");
    check("a plain card opens on its window", look(&app), Some(dst), 1.0);
    desktop_event(&app, FOREGROUND, other);
    check("another window in front: it folds away into its window", look(&app), Some(window_rects(frame(win as Hwnd)).0), 0.0);
    desktop_event(&app, FOREGROUND, win);
    check("its window returns: it unfolds again", look(&app), Some(dst), 1.0);
    toggle(&app, "window");
    check("and goes back", look(&app), None, 0.0);

    // A window of the spike's own to push: nothing of the owner's moves.
    let subject = tauri::WebviewWindowBuilder::new(&app, "subject", tauri::WebviewUrl::App("index.html".into()))
        .inner_size(420.0, 300.0)
        .position(200.0, 200.0)
        .focused(false)
        .build()
        .unwrap();
    thread::sleep(Duration::from_millis(500));
    let sub = subject.hwnd().unwrap().0 as isize;
    TEST_FG.store(sub, Ordering::SeqCst);
    let left = || frame(sub as Hwnd).left;
    let strip = || rest("push", frame(sub as Hwnd));
    let left0 = left();

    toggle(&app, "push");
    check("a push card arrives in the strip its window gives up", look(&app), Some(strip()), 1.0);
    report("and its window moved over by the card's width", left() - left0 == CARD_W);
    desktop_event(&app, FOREGROUND, other);
    let s = strip();
    check("another window in front: the push card slides out of the way", look(&app), Some([s[0] - CARD_W / 2, s[1], s[2], s[3]]), 0.0);
    desktop_event(&app, FOREGROUND, sub);
    check("its window returns: the card slides back beside it", look(&app), Some(strip()), 1.0);
    toggle(&app, "push");
    check("put back: the card leaves", look(&app), None, 0.0);
    report("and its window returns to where it was", left() == left0);

    toggle(&app, "push");
    look(&app);
    desktop_event(&app, MOVE_START, sub);
    check("its window is dragged: the push card lets go", look(&app), None, 0.5);
    let mut r = Rect::default();
    unsafe {
        GetWindowRect(sub as Hwnd, &mut r);
        SetWindowPos(sub as Hwnd, std::ptr::null_mut(), r.left + 120, r.top + 40, 0, 0, MOVE_ONLY);
    }
    desktop_event(&app, MOVE_END, sub);
    check("the window is dropped: the card re-settles beside its new place", look(&app), Some(strip()), 1.0);
    let dropped = left();
    toggle(&app, "push");
    check("put back: the card leaves", look(&app), None, 0.0);
    report("and the dragged window stays where it was dropped", left() == dropped);

    // Drawing on top of a control: the page's side, and that Windows answers at all.
    let ctl = [st.origin.0 + 300, st.origin.1 + 300, 200, 40];
    let _ = app.get_webview_window("canvas").unwrap().eval(&format!("mark({},{})", st.arr(ctl), st.arr(card_for(ctl, &st))));
    check("a mark's card opens beside its control", look(&app), Some(card_for(ctl, &st)), 1.0);
    let _ = app.get_webview_window("canvas").unwrap().eval("unmark()");
    check("and leaves", look(&app), None, 0.0);
    let (tx, rx) = mpsc::channel();
    let _ = st.uia.lock().unwrap().send(Uia::Read(tx));
    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(Some(ms)) => println!("info found the focused control in {ms:.0} ms"),
        Ok(None) => println!("info nothing has focus that Windows can describe right now"),
        Err(_) => report("UI Automation answers", false),
    }

    if st.started.load(Ordering::SeqCst) != 10 {
        report(&format!("the webview answered {} of 10 starts", st.started.load(Ordering::SeqCst)), false);
    }
    println!("{}", if failed.get() { "selftest FAILED" } else { "selftest ok" });
    app.exit(failed.get() as i32);
}

fn main() {
    let keys = [
        (Code::KeyW, "window"),
        (Code::KeyA, "ask"),
        (Code::KeyT, "tray"),
        (Code::KeyP, "push"),
        (Code::KeyR, "ring"),
        (Code::KeyQ, "quit"),
    ];
    tauri::Builder::default()
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    match keys.iter().find(|(code, _)| *code == shortcut.key) {
                        Some((_, "quit")) => quit(app),
                        Some((_, "ring")) => ring_key(app),
                        Some((_, kind)) => toggle(app, kind),
                        None => {}
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![started, probe])
        .setup(move |app| {
            let win = app.get_webview_window("canvas").unwrap();
            let mon = win.primary_monitor()?.ok_or("no monitor")?;
            win.set_position(*mon.position())?;
            // One pixel short: a topmost window covering the whole monitor counts as full
            // screen, and Windows then holds notifications back.
            win.set_size(PhysicalSize::new(mon.size().width, mon.size().height - 1))?;
            win.set_ignore_cursor_events(true)?;
            let (tx, rx) = mpsc::channel();
            app.manage(St {
                origin: (mon.position().x, mon.position().y),
                size: (mon.size().width as i32, mon.size().height as i32),
                uia: Mutex::new(tx),
                open: Mutex::new(None),
                pending: Mutex::new(None),
                started: AtomicU32::new(0),
                seen: Mutex::new(None),
            });
            let _ = APP.set(app.handle().clone());
            let for_uia = app.handle().clone();
            thread::spawn(move || uia_thread(for_uia, rx));

            // Three system events, each rare: who is in front, and a drag's start and end.
            // Delivered on this thread's message loop. Flag 2 skips events our own process
            // raises; the selftest raises its own, so it listens to them.
            let selftest_run = std::env::args().any(|a| a == "--selftest");
            let hook = unsafe {
                SetWinEventHook(FOREGROUND, MOVE_END, std::ptr::null_mut(), on_win_event, 0, 0, if selftest_run { 0 } else { 2 })
            };
            if hook.is_null() {
                println!("the desktop event hook failed: cards won't follow their windows");
            }
            if selftest_run {
                let app = app.handle().clone();
                thread::spawn(move || selftest(app));
                return Ok(());
            }
            for (code, _) in keys {
                let key = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), code);
                if app.global_shortcut().register(key).is_err() {
                    println!("Ctrl+Alt+{code} is taken by another app");
                }
            }
            println!("Ctrl+Alt+W card from the window, A the same but waiting on an answer,");
            println!("T taskbar, P push, R ring on the focused control, Q quit. Same key again puts it back.");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("spike failed to start");
}

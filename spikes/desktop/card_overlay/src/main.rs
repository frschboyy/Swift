//! Spike: the motions of `../card_origin.py`, drawn by a webview as Swift's overlay would.
//!
//! One transparent, click-through window covers the main monitor and never moves. The card
//! is a div inside it, animated by the webview. For the push, the webview says when its
//! animation began and Rust moves the real window from that moment, on the same curve.
//!
//!     cargo run                 Ctrl+Alt+W window, T taskbar, P push, Q quit (same key = back)
//!     cargo run -- --selftest   opens and closes the taskbar card, prints the webview's delay

use std::ffi::c_void;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tauri::{AppHandle, Manager, PhysicalSize, State};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

type Hwnd = *mut c_void;

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
    pushed: Option<(isize, i32, i32)>, // the window and where it was
}

struct St {
    origin: (i32, i32),
    open: Mutex<Option<Open>>,
    pending: Mutex<Option<Move>>,
    started: AtomicU32,
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

fn tray() -> Rect {
    // shortcut: the whole notification area, not one icon; a single icon's rect needs UI Automation
    let mut r = Rect::default();
    unsafe {
        let bar = FindWindowW(wide("Shell_TrayWnd").as_ptr(), std::ptr::null());
        let area = FindWindowExW(bar, std::ptr::null_mut(), wide("TrayNotifyWnd").as_ptr(), std::ptr::null());
        GetWindowRect(if area.is_null() { bar } else { area }, &mut r);
    }
    r
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

fn toggle(app: &AppHandle, kind: &'static str) {
    let st = app.state::<St>();
    let win = app.get_webview_window("canvas").unwrap();
    let mut open = st.open.lock().unwrap();
    if let Some(o) = open.as_ref() {
        if o.kind != kind {
            println!("put the open card back first (same key again)");
            return;
        }
        if let Some((hwnd, x0, y0)) = o.pushed {
            *st.pending.lock().unwrap() = Some(Move { hwnd, from: x0 + CARD_W, to: x0, y: y0, delay_ms: 0 });
        }
        *open = None;
        let _ = win.eval(&format!("go(null,{})", now_ms()));
        return;
    }

    // Read where the source is, once.
    let (src, dst, pushed) = if kind == "tray" {
        let r = tray();
        let (cx, cy) = ((r.left + r.right) / 2, (r.top + r.bottom) / 2);
        ([cx - 12, cy - 12, 24, 24], [(r.right - 352).max(0), r.top - 172, 340, 160], None)
    } else {
        let h = unsafe { GetForegroundWindow() };
        if h.is_null() {
            println!("no active window");
            return;
        }
        let f = frame(h);
        if kind == "window" {
            let cx = (f.left + f.right) / 2;
            ([cx - 30, f.top, 60, 6], [cx - 180, f.top + 44, 360, 180], None)
        } else {
            if unsafe { IsZoomed(h) } != 0 {
                println!("a maximised window has nowhere to move to");
                return;
            }
            let mut r = Rect::default();
            unsafe { GetWindowRect(h, &mut r) };
            *st.pending.lock().unwrap() =
                Some(Move { hwnd: h as isize, from: r.left, to: r.left + CARD_W, y: r.top, delay_ms: APPROACH_MS });
            ([0; 4], [f.left, f.top, CARD_W, f.bottom - f.top], Some((h as isize, r.left, r.top)))
        }
    };
    *open = Some(Open { kind, pushed });
    let (ox, oy) = st.origin;
    let arr = |r: [i32; 4]| format!("[{},{},{},{}]", r[0] - ox, r[1] - oy, r[2], r[3]);
    let _ = win.eval(&format!(
        "go({{kind:'{kind}',src:{},dst:{},grow:{GROW_MS},approach:{APPROACH_MS},push:{PUSH_MS}}},{})",
        arr(src),
        arr(dst),
        now_ms()
    ));
}

fn quit(app: &AppHandle) {
    // Never leave the owner's window where the spike put it.
    if let Some(Open { pushed: Some((hwnd, x0, y0)), .. }) = app.state::<St>().open.lock().unwrap().take() {
        unsafe { SetWindowPos(hwnd as Hwnd, std::ptr::null_mut(), x0, y0, 0, 0, MOVE_ONLY) };
    }
    app.exit(0);
}

fn main() {
    let keys = [(Code::KeyW, "window"), (Code::KeyT, "tray"), (Code::KeyP, "push"), (Code::KeyQ, "quit")];
    tauri::Builder::default()
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    match keys.iter().find(|(code, _)| *code == shortcut.key) {
                        Some((_, "quit")) => quit(app),
                        Some((_, kind)) => toggle(app, kind),
                        None => {}
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![started])
        .setup(move |app| {
            let win = app.get_webview_window("canvas").unwrap();
            let mon = win.primary_monitor()?.ok_or("no monitor")?;
            win.set_position(*mon.position())?;
            // One pixel short: a topmost window covering the whole monitor counts as full
            // screen, and Windows then holds notifications back.
            win.set_size(PhysicalSize::new(mon.size().width, mon.size().height - 1))?;
            win.set_ignore_cursor_events(true)?;
            app.manage(St {
                origin: (mon.position().x, mon.position().y),
                open: Mutex::new(None),
                pending: Mutex::new(None),
                started: AtomicU32::new(0),
            });

            if std::env::args().any(|a| a == "--selftest") {
                let app = app.handle().clone();
                thread::spawn(move || {
                    thread::sleep(Duration::from_secs(3)); // let the page load
                    for _ in 0..2 {
                        toggle(&app, "tray");
                        thread::sleep(Duration::from_millis(700));
                    }
                    let n = app.state::<St>().started.load(Ordering::SeqCst);
                    println!("{}", if n == 2 { "selftest ok" } else { "selftest FAILED: the webview didn't answer twice" });
                    app.exit(if n == 2 { 0 } else { 1 });
                });
                return Ok(());
            }
            for (code, _) in keys {
                let key = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), code);
                if app.global_shortcut().register(key).is_err() {
                    println!("Ctrl+Alt+{code} is taken by another app");
                }
            }
            println!("Ctrl+Alt+W window, T taskbar, P push, Q quit. Same key again puts the card back.");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("spike failed to start");
}

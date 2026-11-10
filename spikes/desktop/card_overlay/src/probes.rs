//! One small probe for each "keep" and each "drop" of the four directions, so the owner
//! judges them by eye instead of taking a claim on trust. Throwaway by design.
//!
//! | Direction               | Keep                                  | Drop                                     |
//! |-------------------------|---------------------------------------|------------------------------------------|
//! | Swift reacts to Windows | 1: a stand-in for Swift reacts to     | 2: a bar glued to the active window,     |
//! |                         |    windows coming forward, being      |    moved on every frame of a drag        |
//! |                         |    picked up, dropped and minimised   |                                          |
//! | Windows reacts to Swift | 3: the desktop dims behind a card     | 4: a live copy of the active window      |
//! |                         |    (the push is the P key)            |    swells and settles                    |
//! | They move as one        | minimise a window that has a W card:  | switch virtual desktop with a W card     |
//! |                         | the card sweeps into the taskbar      | open: the terminal says what Swift saw   |
//! | Made of the same stuff  | 7: a card of Windows' own blur;       | 8: a card tinted by the colour of        |
//! |                         |    rings take Windows' accent colour  |    what's underneath it                  |

use std::ffi::c_void;
use std::sync::atomic::{AtomicBool, AtomicIsize, AtomicU32, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::window::{Effect, EffectsBuilder};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use windows::Win32::Foundation::{HWND, RECT};
use windows::Win32::Graphics::Dwm::{
    DwmGetColorizationColor, DwmRegisterThumbnail, DwmUnregisterThumbnail, DwmUpdateThumbnailProperties,
    DWM_THUMBNAIL_PROPERTIES, DWM_TNP_OPACITY, DWM_TNP_RECTDESTINATION, DWM_TNP_VISIBLE,
};
use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, CLSCTX_ALL, COINIT_MULTITHREADED};
use windows::Win32::UI::Shell::{IVirtualDesktopManager, VirtualDesktopManager};

use crate::{
    desktop_event, frame, home, on_win_event, taskbar, tray, DwmFlush, GetForegroundWindow, GetWindowRect, Hwnd, Rect,
    SetWinEventHook, St, FOREGROUND, MIN_START, MOVE_END, MOVE_START, TEST_FG,
};

#[link(name = "advapi32")]
extern "system" {
    fn RegGetValueW(key: isize, sub: *const u16, value: *const u16, flags: u32, kind: *mut u32, data: *mut c_void, size: *mut u32) -> i32;
}

/// Windows' own "Transparency effects" switch. Off, Windows draws its blur materials solid.
fn transparency_on() -> bool {
    let (mut on, mut size) = (1u32, 4u32);
    let hkcu = 0x8000_0001u32 as i32 as isize;
    let key = crate::wide("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize");
    let value = crate::wide("EnableTransparency");
    unsafe { RegGetValueW(hkcu, key.as_ptr(), value.as_ptr(), 0x10, std::ptr::null_mut(), &mut on as *mut _ as _, &mut size) };
    on != 0
}

#[link(name = "user32")]
extern "system" {
    fn GetWindowThreadProcessId(h: Hwnd, pid: *mut u32) -> u32;
    fn UnhookWinEvent(hook: Hwnd) -> i32;
    fn GetDC(h: Hwnd) -> Hwnd;
    fn ReleaseDC(h: Hwnd, dc: Hwnd) -> i32;
}
#[link(name = "gdi32")]
extern "system" {
    fn GetPixel(dc: Hwnd, x: i32, y: i32) -> u32;
}

pub const LOCATION: u32 = 0x800B; // EVENT_OBJECT_LOCATIONCHANGE

static PRESENCE: AtomicBool = AtomicBool::new(false);
static STEPPED_ASIDE: AtomicBool = AtomicBool::new(false);
static DIM: AtomicBool = AtomicBool::new(false);
static GLUE: AtomicIsize = AtomicIsize::new(0); // the window the bar is glued to
static GLUE_HOOK: AtomicIsize = AtomicIsize::new(0);
static GLUE_MOVES: AtomicU32 = AtomicU32::new(0);
static GLUE_SINCE: Mutex<Option<Instant>> = Mutex::new(None);

fn eval(app: &AppHandle, js: &str) {
    let _ = app.get_webview_window("canvas").unwrap().eval(js);
}

fn active() -> Hwnd {
    let test = TEST_FG.load(Ordering::SeqCst);
    if test != 0 {
        test as Hwnd
    } else {
        unsafe { GetForegroundWindow() }
    }
}

/// Where the stand-in for Swift rests: left of the home spot, just above the taskbar.
fn pill_home() -> [i32; 4] {
    let r = tray();
    [(r.right - 500).max(0), r.top - 52, 120, 36]
}

pub fn key(app: &AppHandle, which: &str) {
    let st = app.state::<St>();
    match which {
        "probe1" => {
            let on = !PRESENCE.fetch_xor(true, Ordering::SeqCst);
            STEPPED_ASIDE.store(false, Ordering::SeqCst);
            eval(app, &format!("pill({on},{})", st.arr(pill_home())));
            println!("presence: {}", if on { "shown. Bring windows forward, drag them, drop one on it, minimise one" } else { "put away" });
        }
        "probe2" => glue_key(app),
        "probe3" => {
            if st.open.lock().unwrap().is_some() {
                return println!("put the open card back first (same key again)");
            }
            let on = !DIM.fetch_xor(true, Ordering::SeqCst);
            eval(app, &format!("dim({on})"));
            println!("dim: {}", if on { "the desktop dims behind a card" } else { "lifted" });
        }
        "probe4" => {
            let (app, src) = (app.clone(), active() as isize);
            thread::spawn(move || match swell(&app, src) {
                Ok(n) => println!("swell: a live copy of the window swelled and settled over {n} frames"),
                Err(e) => println!("swell: Windows wouldn't draw a live copy of that window: {e}"),
            });
        }
        "probe7" => glass(app),
        _ => {}
    }
}

/// Every window event passes through here on its way to the cards.
pub fn window_event(app: &AppHandle, event: u32, hwnd: isize) {
    presence_event(app, event, hwnd);
    // The dim is for the moment a card needs you: turning to another window ends it.
    if event == FOREGROUND && DIM.swap(false, Ordering::SeqCst) {
        eval(app, "dim(false)");
        println!("dim: lifted, you turned to another window");
    }
    // The glued bar belongs to whichever window is in front, and to none that's minimised.
    let glued = GLUE.load(Ordering::SeqCst);
    if glued != 0 && event == FOREGROUND && hwnd != glued {
        glue_to(app, hwnd as Hwnd);
    } else if hwnd == glued && event == MIN_START {
        eval(app, "glue(null)");
    }
}

/// Keep 1: the stand-in for Swift reacts when things start and end. Never per frame.
fn presence_event(app: &AppHandle, event: u32, hwnd: isize) {
    if !PRESENCE.load(Ordering::SeqCst) {
        return;
    }
    let (f, p) = (frame(hwnd as Hwnd), pill_home());
    if f.right <= f.left {
        return;
    }
    // Which way the window is from Swift, as a unit vector.
    let (dx, dy) = (((f.left + f.right) / 2 - p[0] - p[2] / 2) as f64, ((f.top + f.bottom) / 2 - p[1] - p[3] / 2) as f64);
    let len = (dx * dx + dy * dy).sqrt().max(1.0);
    let (dx, dy) = (dx / len, dy / len);
    let st = app.state::<St>();
    let (said, js) = match event {
        FOREGROUND => ("nods toward the window that came forward", format!("pillReact('nod',{dx:.2},{dy:.2})")),
        MOVE_START => ("leans toward the window you picked up", format!("pillReact('lean',{dx:.2},{dy:.2})")),
        MIN_START => ("dips as the window goes down", "pillReact('nod',0,1)".to_string()),
        MOVE_END => {
            let on_it = f.left < p[0] + p[2] && f.right > p[0] && f.top < p[1] + p[3] && f.bottom > p[1];
            if on_it {
                STEPPED_ASIDE.store(true, Ordering::SeqCst);
                // Above the window if there's room, else to its left.
                let to = if f.top - 44 >= st.origin.1 { [p[0], f.top - 44, p[2], p[3]] } else { [(f.left - 128).max(st.origin.0), p[1], p[2], p[3]] };
                ("steps aside: a window was dropped on it", format!("pillReact('rest',0,0);pillMove({})", st.arr(to)))
            } else if STEPPED_ASIDE.swap(false, Ordering::SeqCst) {
                ("goes back to its place: the window left", format!("pillReact('rest',0,0);pillMove({})", st.arr(p)))
            } else {
                ("settles as the window is dropped", "pillReact('rest',0,0)".to_string())
            }
        }
        _ => return,
    };
    println!("presence: {said}");
    eval(app, &js);
}

/// Drop 1: a bar glued to the active window and moved on every frame it moves.
fn glue_key(app: &AppHandle) {
    if GLUE.load(Ordering::SeqCst) != 0 {
        unsafe { UnhookWinEvent(GLUE_HOOK.swap(0, Ordering::SeqCst) as Hwnd) };
        GLUE.store(0, Ordering::SeqCst);
        eval(app, "glue(null)");
        let secs = GLUE_SINCE.lock().unwrap().take().map_or(0.0, |t| t.elapsed().as_secs_f64());
        return println!("glue: off. The window reported {} moves in {secs:.0} s", GLUE_MOVES.swap(0, Ordering::SeqCst));
    }
    let h = active();
    if h.is_null() {
        return println!("no active window");
    }
    *GLUE_SINCE.lock().unwrap() = Some(Instant::now());
    println!("glue: a bar is glued to the active window's top edge. Drag the window and watch whether it keeps up");
    glue_to(app, h);
}

/// Listen to this window's moves, in place of whichever window the bar was on.
fn glue_to(app: &AppHandle, h: Hwnd) {
    let old = GLUE_HOOK.swap(0, Ordering::SeqCst);
    if old != 0 {
        unsafe { UnhookWinEvent(old as Hwnd) };
    }
    let mut pid = 0;
    unsafe { GetWindowThreadProcessId(h, &mut pid) };
    // Only this window's process: a hook on everything drowns in cursor moves.
    let hook = unsafe { SetWinEventHook(LOCATION, LOCATION, std::ptr::null_mut(), on_win_event, pid, 0, 2) };
    GLUE_HOOK.store(hook as isize, Ordering::SeqCst);
    GLUE.store(h as isize, Ordering::SeqCst);
    glue_event(app, h as isize);
}

pub fn glue_event(app: &AppHandle, hwnd: isize) {
    if hwnd != GLUE.load(Ordering::SeqCst) {
        return;
    }
    GLUE_MOVES.fetch_add(1, Ordering::SeqCst);
    let f = frame(hwnd as Hwnd);
    if f.left < -30000 {
        return eval(app, "glue(null)"); // minimised: Windows parks it far off screen
    }
    eval(app, &format!("glue({})", app.state::<St>().arr([(f.left + f.right) / 2 - 80, f.top - 3, 160, 6])));
}

/// Drop 2: make a real window look as if it swells, by drawing a live copy of it (one
/// Windows keeps up to date itself) on top and resizing the copy. The window isn't touched.
pub fn swell(app: &AppHandle, src: isize) -> Result<u32, String> {
    let st = app.state::<St>();
    let canvas = app.get_webview_window("canvas").unwrap().hwnd().map_err(|e| e.to_string())?;
    let copy = unsafe { DwmRegisterThumbnail(canvas, HWND(src as _)) }.map_err(|e| e.to_string())?;
    let f = frame(src as Hwnd);
    let (w, h) = ((f.right - f.left) as f64, (f.bottom - f.top) as f64);
    let (t0, mut frames, mut result) = (Instant::now(), 0, Ok(0));
    loop {
        unsafe { DwmFlush() };
        let u = (t0.elapsed().as_secs_f64() / 0.36).min(1.0);
        let grow = 0.04 * (u * std::f64::consts::PI).sin(); // out and back
        let (gx, gy) = ((w * grow / 2.0) as i32, (h * grow / 2.0) as i32);
        let props = DWM_THUMBNAIL_PROPERTIES {
            dwFlags: DWM_TNP_RECTDESTINATION | DWM_TNP_VISIBLE | DWM_TNP_OPACITY,
            rcDestination: RECT {
                left: f.left - st.origin.0 - gx,
                top: f.top - st.origin.1 - gy,
                right: f.right - st.origin.0 + gx,
                bottom: f.bottom - st.origin.1 + gy,
            },
            opacity: 255,
            fVisible: true.into(),
            ..Default::default()
        };
        if let Err(e) = unsafe { DwmUpdateThumbnailProperties(copy, &props) } {
            result = Err(e.to_string());
            break;
        }
        frames += 1;
        if u >= 1.0 {
            break;
        }
    }
    let _ = unsafe { DwmUnregisterThumbnail(copy) };
    result.map(|_: u32| frames)
}

/// Where the glass card sits: above the home spot.
fn glass_spot() -> [i32; 4] {
    let h = home();
    [h[0], h[1] - 180, h[2], h[3]]
}

/// A window of its own for a material, because a material belongs to a whole window.
/// Placed and sized as it's made: made first and moved after, it flashed for a moment at
/// Windows' default spot, which the owner saw as another card flickering.
fn build_glass(app: &AppHandle, label: &str, effect: Effect) -> tauri::Result<tauri::WebviewWindow> {
    let h = glass_spot();
    let scale = app.get_webview_window("canvas").and_then(|c| c.scale_factor().ok()).unwrap_or(1.0);
    WebviewWindowBuilder::new(app, label, WebviewUrl::App("index.html".into()))
        .position(h[0] as f64 / scale, h[1] as f64 / scale)
        .inner_size(h[2] as f64 / scale, h[3] as f64 / scale)
        .transparent(true)
        .decorations(false)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .resizable(false)
        .effects(EffectsBuilder::new().effect(effect).build())
        .build()
}

#[repr(C)]
struct AccentPolicy {
    state: u32,
    flags: u32,
    colour: u32, // AABBGGRR
    animation: u32,
}
#[repr(C)]
struct CompositionData {
    attribute: u32,
    data: *mut AccentPolicy,
    size: usize,
}
#[link(name = "kernel32")]
extern "system" {
    fn GetModuleHandleW(name: *const u16) -> Hwnd;
    fn GetProcAddress(module: Hwnd, name: *const u8) -> Option<unsafe extern "system" fn(Hwnd, *mut CompositionData) -> i32>;
}

/// The older acrylic, through a call Windows doesn't document. Tools that put blur behind
/// windows that never have focus use it. Undocumented means it can stop working in any
/// Windows update.
fn old_acrylic(h: Hwnd, colour: u32) -> bool {
    unsafe {
        let Some(set) = GetProcAddress(GetModuleHandleW(crate::wide("user32.dll").as_ptr()), b"SetWindowCompositionAttribute\0".as_ptr()) else {
            return false;
        };
        let mut policy = AccentPolicy { state: 4, flags: 2, colour, animation: 0 }; // 4 = acrylic blur behind
        set(h, &mut CompositionData { attribute: 19, data: &mut policy, size: 16 }) != 0 // 19 = accent policy
    }
}

/// What the screen really shows across the glass spot: brightness at 40 points along a row.
fn row(r: [i32; 4]) -> Vec<u32> {
    unsafe {
        let dc = GetDC(std::ptr::null_mut());
        let v = (0..40)
            .map(|i| {
                let c = GetPixel(dc, r[0] + 6 + (r[2] - 12) * i / 39, r[1] + r[3] / 2);
                ((c & 255) + (c >> 8 & 255) + (c >> 16 & 255)) / 3
            })
            .collect();
        ReleaseDC(std::ptr::null_mut(), dc);
        v
    }
}

/// Black and white bands read back as: untouched (only blacks and whites), frosted (greys
/// in between), or hidden (one flat colour).
fn read_bands(v: &[u32]) -> String {
    let (lo, hi) = (*v.iter().min().unwrap(), *v.iter().max().unwrap());
    let between = v.iter().filter(|&&x| x > lo + 12 && x + 12 < hi).count();
    let what = if hi - lo < 12 {
        "HIDDEN: one flat colour, the bands don't come through"
    } else if between <= 3 {
        "SHARP: the bands come through untouched"
    } else {
        "FROSTED: the bands come through softened"
    };
    format!("{what} (darkest {lo}, brightest {hi}, {between} of 40 points in between)")
}

/// Which of Windows' materials really blur what's behind a window that never has focus?
/// Measured from the screen, not judged by eye. `cargo run -- --glasstest`
///
/// Result (2026-11-11, owner's PC, Windows build 26300, transparency effects on): none.
/// Acrylic frosts only while its window has focus. Mica and tabbed never show what's
/// behind. The older blur and acrylic draw a flat colour. A frosted card that never takes
/// focus would have to be drawn by Swift from a capture of the screen.
pub fn glass_test(app: AppHandle) {
    thread::sleep(Duration::from_secs(3)); // let the page load
    let spot = glass_spot();
    println!("transparency effects in Windows' settings: {}", if transparency_on() { "on" } else { "OFF" });
    eval(&app, &format!("stripes({})", app.state::<St>().arr(spot)));
    thread::sleep(Duration::from_millis(600));
    println!("{:<22} {}", "no material", read_bands(&row(spot)));
    let materials = [("acrylic", Effect::Acrylic), ("blur", Effect::Blur), ("mica", Effect::Mica), ("tabbed", Effect::Tabbed)];
    for (i, (name, effect)) in materials.into_iter().enumerate() {
        match build_glass(&app, &format!("glasstest{i}"), effect) {
            Ok(w) => {
                let _ = w.set_ignore_cursor_events(true);
                thread::sleep(Duration::from_millis(1200));
                println!("{name:<22} {}", read_bands(&row(spot)));
                // Windows may keep its materials for the window being worked in. Swift's
                // cards never take focus, so measure both ways.
                let _ = w.set_focus();
                thread::sleep(Duration::from_millis(900));
                println!("{:<22} {}", format!("{name}, with focus"), read_bands(&row(spot)));
                let _ = w.close();
                thread::sleep(Duration::from_millis(500));
            }
            Err(e) => println!("{name:<22} couldn't be made: {e}"),
        }
    }
    // Never focused, with a heavy and then a light tint (the top byte is how opaque).
    for (i, colour) in [0x6620_2020u32, 0x1020_2020, 0x0120_2020].into_iter().enumerate() {
        match build_glass(&app, &format!("glassold{i}"), Effect::Blur) {
            Ok(w) => {
                let _ = w.set_ignore_cursor_events(true);
                let took = w.hwnd().map(|h| old_acrylic(h.0 as Hwnd, colour)).unwrap_or(false);
                thread::sleep(Duration::from_millis(1200));
                let name = format!("old acrylic {:#04x}", colour >> 24);
                println!("{name:<22} {}{}", read_bands(&row(spot)), if took { "" } else { " (Windows refused the call)" });
                let _ = w.close();
                thread::sleep(Duration::from_millis(500));
            }
            Err(e) => println!("old acrylic couldn't be made: {e}"),
        }
    }
    eval(&app, "stripes(null)");
    app.exit(0);
}

/// Keep 4: a card made of Windows' own blur material.
fn glass(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("glass") {
        let _ = w.close();
        return println!("glass: put away");
    }
    let app = app.clone();
    thread::spawn(move || {
        let built = build_glass(&app, "glass", Effect::Acrylic);
        match built {
            Ok(w) => {
                // Square corners: rounding them brings Windows' shadow, which arrived late.
                let _ = w.set_ignore_cursor_events(true);
                if transparency_on() {
                    println!("glass: this card is solid. Windows draws its blur only for the window that has focus,");
                    println!("glass: and Swift's cards never take focus. Measured by: cargo run -- --glasstest");
                } else {
                    println!("glass: Windows' transparency effects are turned off on this PC, so Windows draws this card solid.");
                    println!("glass: the switch is in Settings > Personalisation > Colours. Swift should respect it either way");
                }
            }
            Err(e) => println!("glass: couldn't make the window: {e}"),
        }
    });
}

/// Drop 4: the colour of what's under a spot, read once from the screen. Nine pixels,
/// averaged to one colour, kept nowhere.
pub fn sample(r: [i32; 4]) -> u32 {
    let (mut sum, mut n) = ([0u32; 3], 0);
    unsafe {
        let dc = GetDC(std::ptr::null_mut());
        for i in 1..4 {
            for j in 1..4 {
                let c = GetPixel(dc, r[0] + r[2] * i / 4, r[1] + r[3] * j / 4); // 0x00bbggrr
                if c != u32::MAX {
                    sum = [sum[0] + (c & 255), sum[1] + (c >> 8 & 255), sum[2] + (c >> 16 & 255)];
                    n += 1;
                }
            }
        }
        ReleaseDC(std::ptr::null_mut(), dc);
    }
    let n = n.max(1);
    (sum[0] / n) << 16 | (sum[1] / n) << 8 | sum[2] / n
}

/// Runs for the life of the app: Windows' accent colour once the page is up, then the
/// virtual desktop watch (drop 3).
pub fn start(app: AppHandle) {
    thread::spawn(move || {
        thread::sleep(Duration::from_secs(2));
        let (mut argb, mut opaque) = (0u32, Default::default());
        if unsafe { DwmGetColorizationColor(&mut argb, &mut opaque) }.is_ok() {
            eval(&app, &format!("accent('#{:06x}')", argb & 0xff_ffff));
            println!("accent: rings and waiting cards take Windows' accent colour, #{:06x}", argb & 0xff_ffff);
        }

        let desks: IVirtualDesktopManager = unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            match CoCreateInstance(&VirtualDesktopManager, None, CLSCTX_ALL) {
                Ok(d) => d,
                Err(e) => return println!("virtual desktops: Windows won't say which desktop a window is on: {e}"),
            }
        };
        let mut last: Option<(isize, bool)> = None;
        loop {
            thread::sleep(Duration::from_millis(200));
            let st = app.state::<St>();
            let hwnd = st.open.lock().unwrap().as_ref().map(|o| o.hwnd).filter(|h| *h != 0);
            let Some(h) = hwnd else {
                last = None;
                continue;
            };
            let Ok(here) = (unsafe { desks.IsWindowOnCurrentVirtualDesktop(HWND(h as _)) }) else { continue };
            let here = here.as_bool();
            if last == Some((h, !here)) {
                println!("virtual desktops: the card's window is {}", if here { "back on this desktop" } else { "on another desktop now" });
                desktop_event(&app, FOREGROUND, if here { h } else { 1 });
            }
            last = Some((h, here));
        }
    });
}

/// Selftest: the taskbar's own rectangle, where a minimised window's card goes.
pub fn taskbar_spot() -> [i32; 4] {
    let mut t = Rect::default();
    unsafe { GetWindowRect(taskbar(), &mut t) };
    [(t.left + t.right) / 2 - 20, t.top + 4, 40, 8]
}

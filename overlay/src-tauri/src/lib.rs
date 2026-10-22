//! Swift overlay shell: one transparent, non-activating, click-through,
//! capture-excluded window; global hotkeys; tray; the Python backend's lifetime.
//! See PLAN.md §1 and §5.

mod backend;
mod hit;
mod placement;
mod win;

use std::collections::HashMap;
use std::sync::{Arc, Condvar, Mutex};
use std::time::Instant;

use serde::Serialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewWindow};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

use backend::{BackendInfo, SharedBackend};
use hit::{Geometry, HitState, Rect, SharedHit};

struct Overlay {
    hwnd: isize,
    capture_excluded: bool,
}

/// When this process started, for the startup-time measurement.
struct Started(Instant);

/// Registered shortcut id -> logical name ("push_to_talk", "debug", "escape").
#[derive(Default)]
struct Hotkeys(Mutex<HashMap<u32, (String, Shortcut)>>);

#[derive(Clone, Serialize)]
struct HotkeyEvent {
    name: String,
    state: &'static str,
}

fn place_on_cursor_monitor(window: &WebviewWindow, hwnd: isize, hit: &SharedHit) {
    let Some((cx, cy)) = win::cursor_pos() else {
        eprintln!("[overlay] place: GetCursorPos failed");
        return;
    };
    let monitor = window
        .monitor_from_point(cx as f64, cy as f64)
        .ok()
        .flatten()
        .or_else(|| window.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else {
        eprintln!("[overlay] place: no monitor for cursor ({cx}, {cy})");
        return;
    };

    let scale = monitor.scale_factor();
    let wa = monitor.work_area();
    let area = placement::Area { x: wa.position.x, y: wa.position.y, w: wa.size.width, h: wa.size.height };
    let (x, y, w, h) = placement::overlay_rect(area, scale);

    // Twice: crossing into a monitor with a different DPI makes Windows resize
    // the window during the first call (WM_DPICHANGED); the second restores our rect.
    win::place(hwnd, x, y, w, h);
    win::place(hwnd, x, y, w, h);
    win::ensure_styles(hwnd);

    eprintln!("[overlay] placed at {x},{y} {w}x{h} (scale {scale})");
    hit.0.lock().unwrap().geometry = Geometry { x, y, scale };
}

fn place_on_main(app: &AppHandle) {
    let app2 = app.clone();
    let _ = app.run_on_main_thread(move || {
        let (Some(window), Some(overlay)) = (
            app2.get_webview_window("overlay"),
            app2.try_state::<Overlay>(),
        ) else {
            return;
        };
        let hit = app2.state::<SharedHit>();
        place_on_cursor_monitor(&window, overlay.hwnd, &hit);
    });
}

fn on_shortcut(app: &AppHandle, shortcut: &Shortcut, state: ShortcutState) {
    let name = {
        let keys = app.state::<Hotkeys>();
        let map = keys.0.lock().unwrap();
        match map.get(&shortcut.id()) {
            Some((name, _)) => name.clone(),
            None => return,
        }
    };
    let state = match state {
        ShortcutState::Pressed => "down",
        ShortcutState::Released => "up",
    };
    eprintln!("[overlay] hotkey {name} {state}");
    if state == "down" && name != "escape" {
        place_on_main(app);
    }
    let _ = app.emit("hotkey", HotkeyEvent { name, state });
}

fn register(app: &AppHandle, name: &str, spec: &str) -> Result<(), String> {
    let shortcut: Shortcut = spec
        .parse()
        .map_err(|e| format!("{name}: cannot parse '{spec}': {e}"))?;
    let keys = app.state::<Hotkeys>();
    let mut map = keys.0.lock().unwrap();
    if let Some((_, old)) = map.iter().find(|(_, (n, _))| n == name).map(|(id, v)| (*id, v.1)) {
        let _ = app.global_shortcut().unregister(old);
        map.retain(|_, (n, _)| n != name);
    }
    app.global_shortcut()
        .register(shortcut)
        .map_err(|e| format!("{name}: cannot register '{spec}' (in use by another app?): {e}"))?;
    map.insert(shortcut.id(), (name.to_string(), shortcut));
    eprintln!("[overlay] registered {name} = {spec}");
    Ok(())
}

fn unregister(app: &AppHandle, name: &str) {
    let keys = app.state::<Hotkeys>();
    let mut map = keys.0.lock().unwrap();
    let ids: Vec<u32> = map.iter().filter(|(_, (n, _))| n == name).map(|(id, _)| *id).collect();
    for id in ids {
        if let Some((_, sc)) = map.remove(&id) {
            let _ = app.global_shortcut().unregister(sc);
        }
    }
}

// ---- commands (async, so they never run on the main thread) ----------------

#[tauri::command]
async fn backend_info(backend: State<'_, SharedBackend>) -> Result<BackendInfo, String> {
    let b = backend.lock().unwrap();
    match (&b.info, &b.error) {
        (Some(info), _) => Ok(info.clone()),
        (None, Some(err)) => Err(err.clone()),
        (None, None) => Err("starting".into()),
    }
}

/// Registers the configured hotkeys. Returns one message per hotkey that failed.
#[tauri::command]
async fn register_hotkeys(app: AppHandle, hotkeys: HashMap<String, String>) -> Result<Vec<String>, String> {
    let mut problems = Vec::new();
    for (name, spec) in &hotkeys {
        if name == "escape" {
            continue;
        }
        if let Err(e) = register(&app, name, spec) {
            eprintln!("[overlay] hotkey problem: {e}");
            problems.push(e);
        }
    }
    Ok(problems)
}

/// Esc is grabbed only while Swift is active: RegisterHotKey consumes it system-wide.
#[tauri::command]
async fn set_escape(app: AppHandle, active: bool) -> Result<(), String> {
    if active {
        register(&app, "escape", "Escape")
    } else {
        unregister(&app, "escape");
        Ok(())
    }
}

#[tauri::command]
async fn set_hit_regions(hit: State<'_, SharedHit>, rects: Vec<Rect>) -> Result<(), String> {
    let (lock, cvar) = &**hit;
    lock.lock().unwrap().rects = rects;
    cvar.notify_all();
    Ok(())
}

#[derive(Serialize)]
struct Startup {
    /// Process start to this call (the overlay connected and hotkeys registered).
    startup_ms: u128,
    /// Process start to the backend's ready line, if it has been seen.
    backend_ms: Option<u128>,
}

/// Called once by the overlay when it's fully ready.
#[tauri::command]
async fn overlay_ready(started: State<'_, Started>, backend: State<'_, SharedBackend>) -> Result<Startup, String> {
    let startup_ms = started.0.elapsed().as_millis();
    let backend_ms = backend.lock().unwrap().ready_at.map(|t| t.duration_since(started.0).as_millis());
    eprintln!("[overlay] ready in {startup_ms} ms (backend ready at {backend_ms:?} ms)");
    Ok(Startup { startup_ms, backend_ms })
}

#[derive(Serialize)]
struct Diagnostics {
    ex_style: String,
    no_activate: bool,
    tool_window: bool,
    topmost: bool,
    click_through: bool,
    capture_excluded: bool,
}

/// For the Milestone 1 checks: what the window's styles actually are right now.
#[tauri::command]
async fn diagnostics(overlay: State<'_, Overlay>) -> Result<Diagnostics, String> {
    use windows_sys::Win32::UI::WindowsAndMessaging::{WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST};
    let ex = win::ex_style(overlay.hwnd);
    Ok(Diagnostics {
        ex_style: format!("{ex:#010x}"),
        no_activate: ex & WS_EX_NOACTIVATE as isize != 0,
        tool_window: ex & WS_EX_TOOLWINDOW as isize != 0,
        topmost: ex & WS_EX_TOPMOST as isize != 0,
        click_through: win::is_click_through(overlay.hwnd),
        capture_excluded: overlay.capture_excluded,
    })
}

// ---- app --------------------------------------------------------------------

fn open_logs_folder() {
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        let dir = std::path::Path::new(&local).join("Swift");
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::process::Command::new("explorer.exe").arg(dir).spawn();
    }
}

fn quit(app: &AppHandle) {
    backend::stop(&app.state::<SharedBackend>());
    app.exit(0);
}

pub fn run() {
    let started = Started(Instant::now());
    let shared_backend: SharedBackend = Arc::new(Mutex::new(backend::Backend::default()));
    let shared_hit: SharedHit = Arc::new((Mutex::new(HitState::default()), Condvar::new()));

    let app = tauri::Builder::default()
        // Must be the first plugin. A second launch exits right away; the running
        // overlay says so instead of failing to register the hotkeys. No set_focus():
        // Swift must never take focus.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            eprintln!("[overlay] second launch blocked: Swift is already running");
            place_on_main(app);
            let _ = app.emit("already-running", ());
        }))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| on_shortcut(app, shortcut, event.state()))
                .build(),
        )
        .manage(shared_backend.clone())
        .manage(shared_hit.clone())
        .manage(Hotkeys::default())
        .manage(started)
        .invoke_handler(tauri::generate_handler![
            backend_info,
            register_hotkeys,
            set_escape,
            set_hit_regions,
            overlay_ready,
            diagnostics
        ])
        // The window is created visible (tauri.conf.json): tao shows a window
        // with SW_SHOWNOACTIVATE only at creation when `focus` is false, and a
        // window tao believes hidden is re-hidden on every style change
        // (e.g. toggling click-through). Never call show()/set_focus() on it.
        .setup(move |app| {
            let window = app
                .get_webview_window("overlay")
                .expect("tauri.conf.json defines the overlay window");
            let hwnd = window.hwnd()?.0 as isize;

            let capture_excluded = win::init_overlay(hwnd);
            if !capture_excluded {
                eprintln!("warning: SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) failed");
            }
            app.manage(Overlay { hwnd, capture_excluded });

            place_on_cursor_monitor(&window, hwnd, &shared_hit);
            hit::spawn(window.clone(), hwnd, shared_hit.clone());

            let logs_item = MenuItem::with_id(app, "logs", "Open logs folder", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Swift", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&logs_item, &quit_item])?;
            let mut tray = TrayIconBuilder::with_id("swift")
                .tooltip("Swift")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "logs" => open_logs_folder(),
                    "quit" => quit(app),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            backend::start(app.handle(), shared_backend.clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Swift overlay");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            backend::stop(&app.state::<SharedBackend>());
        }
    });
}

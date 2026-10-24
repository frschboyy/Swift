//! Swift overlay shell: one transparent, non-activating, click-through,
//! capture-excluded window; global hotkeys; tray; the Python backend's lifetime.
//! See PLAN.md §1 and §5. Placement, dragging and the tray's Position menu: ADR-009.

mod backend;
mod hit;
mod placement;
mod prefs;
mod win;

use std::collections::HashMap;
use std::sync::{Arc, Condvar, Mutex};
use std::time::Instant;

use serde::Serialize;
use tauri::menu::{CheckMenuItem, IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewWindow, Wry};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

use backend::{BackendInfo, SharedBackend};
use hit::{Geometry, HitState, Rect, SharedHit};
use placement::Anchor;
use prefs::Prefs;

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

/// Where the overlay is and may go.
#[derive(Default)]
struct PlacementState {
    prefs: Prefs,
    /// Where it is now: `prefs.anchor`, or its flip when smart placement moved it.
    current: Anchor,
    /// An interaction is running (Esc is grabbed): don't flip under the owner's eyes.
    busy: bool,
    dragging: bool,
}

struct Placement(Mutex<PlacementState>);

/// The tray's Position menu, kept to update its checkmarks.
struct TrayItems {
    anchors: Vec<(Anchor, CheckMenuItem<Wry>)>,
    smart: CheckMenuItem<Wry>,
}

#[derive(Clone, Serialize)]
struct PlacementEvent {
    anchor: &'static str,
    /// Smart placement moved it away from the owner's choice.
    flipped: bool,
}

#[derive(Clone, Copy)]
enum Place {
    /// The owner's anchor, flipped away from the text caret if smart placement is on.
    Smart,
    /// Exactly here (the owner just chose it).
    Exact(Anchor),
}

fn place_on_cursor_monitor(app: &AppHandle, window: &WebviewWindow, hwnd: isize, hit: &SharedHit, how: Place) {
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
    let (anchor, flipped) = {
        let state = app.state::<Placement>();
        let mut p = state.0.lock().unwrap();
        let anchor = match how {
            Place::Exact(anchor) => anchor,
            Place::Smart if p.busy => p.current,
            Place::Smart if p.prefs.smart => {
                let caret: Vec<(i32, i32)> = win::caret_pos().into_iter().collect();
                placement::choose_anchor(area, scale, p.prefs.anchor, &caret)
            }
            Place::Smart => p.prefs.anchor,
        };
        p.current = anchor;
        (anchor, anchor != p.prefs.anchor)
    };
    let (x, y, w, h) = placement::overlay_rect(area, scale, anchor);

    // Twice: crossing into a monitor with a different DPI makes Windows resize
    // the window during the first call (WM_DPICHANGED); the second restores our rect.
    win::place(hwnd, x, y, w, h);
    win::place(hwnd, x, y, w, h);
    win::ensure_styles(hwnd);

    eprintln!("[overlay] placed {} at {x},{y} {w}x{h} (scale {scale})", anchor.id());
    hit.0.lock().unwrap().geometry = Geometry { x, y, scale };
    let _ = app.emit("placement", PlacementEvent { anchor: anchor.id(), flipped });
}

fn place_on_main(app: &AppHandle, how: Place) {
    let app2 = app.clone();
    let _ = app.run_on_main_thread(move || {
        let (Some(window), Some(overlay)) = (
            app2.get_webview_window("overlay"),
            app2.try_state::<Overlay>(),
        ) else {
            return;
        };
        let hit = app2.state::<SharedHit>();
        place_on_cursor_monitor(&app2, &window, overlay.hwnd, &hit, how);
    });
}

/// The owner chose where the overlay goes (tray menu or a drag): remember it and move there.
fn choose_anchor(app: &AppHandle, anchor: Anchor) {
    {
        let state = app.state::<Placement>();
        let mut p = state.0.lock().unwrap();
        p.prefs.anchor = anchor;
        prefs::save(&p.prefs);
    }
    sync_tray(app);
    place_on_main(app, Place::Exact(anchor));
}

fn sync_tray(app: &AppHandle) {
    let prefs = app.state::<Placement>().0.lock().unwrap().prefs;
    if let Some(items) = app.try_state::<TrayItems>() {
        for (anchor, item) in &items.anchors {
            let _ = item.set_checked(*anchor == prefs.anchor);
        }
        let _ = items.smart.set_checked(prefs.smart);
    }
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
        place_on_main(app, Place::Smart);
    }
    let _ = app.emit("hotkey", HotkeyEvent { name, state });
}

/// A hotkey that couldn't be registered, for the overlay to explain.
#[derive(Serialize)]
struct HotkeyProblem {
    name: String,
    spec: String,
    /// "invalid": not a shortcut Swift understands. "in_use": another app has it.
    reason: &'static str,
    detail: String,
}

impl std::fmt::Display for HotkeyProblem {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {} '{}': {}", self.name, self.reason, self.spec, self.detail)
    }
}

fn register(app: &AppHandle, name: &str, spec: &str) -> Result<(), HotkeyProblem> {
    let problem = |reason, detail: String| HotkeyProblem { name: name.into(), spec: spec.into(), reason, detail };
    let shortcut: Shortcut = spec.parse().map_err(|e| problem("invalid", format!("{e}")))?;
    let keys = app.state::<Hotkeys>();
    let mut map = keys.0.lock().unwrap();
    if let Some((_, old)) = map.iter().find(|(_, (n, _))| n == name).map(|(id, v)| (*id, v.1)) {
        let _ = app.global_shortcut().unregister(old);
        map.retain(|_, (n, _)| n != name);
    }
    app.global_shortcut()
        .register(shortcut)
        .map_err(|e| problem("in_use", format!("{e}")))?;
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

/// Registers the configured hotkeys. Returns one problem per hotkey that failed.
#[tauri::command]
async fn register_hotkeys(app: AppHandle, hotkeys: HashMap<String, String>) -> Result<Vec<HotkeyProblem>, String> {
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
/// Active also means busy: smart placement leaves the overlay where it is.
#[tauri::command]
async fn set_escape(app: AppHandle, placement: State<'_, Placement>, active: bool) -> Result<(), String> {
    placement.0.lock().unwrap().busy = active;
    if active {
        register(&app, "escape", "Escape").map_err(|p| p.to_string())
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

/// Pointer pressed on a card's drag handle: follow the cursor while the button is held,
/// then snap to the nearest anchor on the monitor it was dropped on and remember it.
/// A press that doesn't move is a click, and changes nothing.
#[tauri::command]
async fn begin_drag(app: AppHandle) -> Result<(), String> {
    {
        let state = app.state::<Placement>();
        let mut p = state.0.lock().unwrap();
        if p.dragging {
            return Ok(());
        }
        p.dragging = true;
    }
    let hwnd = app.state::<Overlay>().hwnd;
    let hit = app.state::<SharedHit>().inner().clone();
    let origin = {
        let g = hit.0.lock().unwrap().geometry;
        (g.x, g.y)
    };
    let Some(start) = win::cursor_pos() else {
        app.state::<Placement>().0.lock().unwrap().dragging = false;
        return Ok(());
    };
    std::thread::spawn(move || {
        let mut last = start;
        let mut moved = false;
        while win::left_button_down() {
            if let Some(c) = win::cursor_pos() {
                let (dx, dy) = (c.0 - start.0, c.1 - start.1);
                if moved || dx.abs() + dy.abs() >= 4 {
                    if !moved {
                        moved = true;
                        let _ = app.emit("drag", true);
                    }
                    if c != last {
                        let (x, y) = (origin.0 + dx, origin.1 + dy);
                        win::move_to(hwnd, x, y);
                        let mut state = hit.0.lock().unwrap();
                        state.geometry.x = x;
                        state.geometry.y = y;
                    }
                }
                last = c;
            }
            std::thread::sleep(std::time::Duration::from_millis(8));
        }
        app.state::<Placement>().0.lock().unwrap().dragging = false;
        if !moved {
            return;
        }
        let _ = app.emit("drag", false);
        let area = app
            .get_webview_window("overlay")
            .and_then(|w| w.monitor_from_point(last.0 as f64, last.1 as f64).ok().flatten())
            .map(|m| {
                let wa = m.work_area();
                placement::Area { x: wa.position.x, y: wa.position.y, w: wa.size.width, h: wa.size.height }
            });
        match area {
            Some(area) => choose_anchor(&app, placement::nearest_anchor(area, last)),
            None => place_on_main(&app, Place::Smart),
        }
    });
    Ok(())
}

/// Where the overlay is now, for the frontend's layout at startup.
#[tauri::command]
async fn get_placement(placement: State<'_, Placement>) -> Result<PlacementEvent, String> {
    let p = placement.0.lock().unwrap();
    Ok(PlacementEvent { anchor: p.current.id(), flipped: p.current != p.prefs.anchor })
}

/// "Copy" on a result card.
#[tauri::command]
async fn copy_text(text: String) -> Result<(), String> {
    win::copy_text(&text)
}

/// "Open logs" on an error card.
#[tauri::command]
async fn open_logs() -> Result<(), String> {
    open_logs_folder();
    Ok(())
}

/// The tray icon's tooltip says whether Swift is ready, so its state is visible without the overlay.
#[tauri::command]
async fn set_status(app: AppHandle, text: String) -> Result<(), String> {
    if let Some(tray) = app.tray_by_id("swift") {
        tray.set_tooltip(Some(text)).map_err(|e| e.to_string())?;
    }
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
            place_on_main(app, Place::Smart);
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
        .manage(Placement(Mutex::new({
            let prefs = prefs::load();
            PlacementState { prefs, current: prefs.anchor, ..Default::default() }
        })))
        .manage(started)
        .invoke_handler(tauri::generate_handler![
            backend_info,
            register_hotkeys,
            set_escape,
            set_hit_regions,
            overlay_ready,
            diagnostics,
            begin_drag,
            get_placement,
            copy_text,
            open_logs,
            set_status
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

            place_on_cursor_monitor(app.handle(), &window, hwnd, &shared_hit, Place::Smart);
            hit::spawn(window.clone(), hwnd, shared_hit.clone());

            // Position: the same choices as dragging a card, for when dragging isn't practical.
            let chosen = app.state::<Placement>().0.lock().unwrap().prefs;
            let mut anchors = Vec::new();
            for anchor in Anchor::ALL {
                let id = format!("anchor:{}", anchor.id());
                let item = CheckMenuItem::with_id(app, id, anchor.label(), true, anchor == chosen.anchor, None::<&str>)?;
                anchors.push((anchor, item));
            }
            let smart = CheckMenuItem::with_id(app, "smart", "Move away from where I'm typing", true, chosen.smart, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let mut position_items: Vec<&dyn IsMenuItem<Wry>> = anchors.iter().map(|(_, i)| i as &dyn IsMenuItem<Wry>).collect();
            position_items.push(&separator);
            position_items.push(&smart);
            let position = Submenu::with_items(app, "Position", true, &position_items)?;
            let logs_item = MenuItem::with_id(app, "logs", "Open logs folder", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Swift", true, None::<&str>)?;
            let separator2 = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&position, &logs_item, &separator2, &quit_item])?;
            app.manage(TrayItems { anchors, smart });
            let mut tray = TrayIconBuilder::with_id("swift")
                .tooltip("Swift: starting")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "logs" => open_logs_folder(),
                    "quit" => quit(app),
                    "smart" => {
                        {
                            let state = app.state::<Placement>();
                            let mut p = state.0.lock().unwrap();
                            p.prefs.smart = !p.prefs.smart;
                            prefs::save(&p.prefs);
                        }
                        sync_tray(app);
                    }
                    id => {
                        if let Some(anchor) = id.strip_prefix("anchor:").and_then(Anchor::from_id) {
                            choose_anchor(app, anchor);
                        }
                    }
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

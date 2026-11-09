//! Swift overlay shell: one transparent, non-activating, click-through,
//! capture-excluded window; global hotkeys; tray; the Python backend's lifetime.
//! See PLAN.md §1 and §5. Placement, dragging and the tray's Position menu: ADR-009.
//! Pane windows (ADR-015): one small window per other request and a reader for long answers,
//! each non-activating, on top and capture-excluded like the main one, sized to its content,
//! dragged anywhere, and remembered per kind.
//! ADR-015 §9, §10 (2026-10-27): the waiting stack is a pane in a bottom corner that grows
//! upwards and folds up on a click anywhere else (`watch_outside`); the text box is the one pane
//! that takes the keyboard, opened by `hotkeys.type` or the tray's "Type to Swift". `pane_labels`
//! lets the main window close any pane it no longer wants.
//! ADR-017 (the Capsule redesign): the overlay follows Windows' light or dark app theme, live
//! (`theme.rs`); a left click on the tray icon opens the tray menu as a pane next to it (the
//! native menu stays on the right click), with Position, smart placement, Pause listening, Type
//! to Swift, Settings (config.yaml in its default app) and Quit.

mod backend;
mod hit;
mod panes;
mod placement;
mod prefs;
mod theme;
mod win;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Instant;

use serde::Serialize;
use tauri::menu::{CheckMenuItem, IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder, Wry};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

use backend::{BackendInfo, SharedBackend};
use hit::{Geometry, HitState, Rect, SharedHit};
use panes::PaneKind;
use placement::Anchor;
use prefs::Prefs;

struct Overlay {
    hwnd: isize,
    capture_excluded: bool,
}

/// Open pane windows: label -> (window handle, kind).
#[derive(Default)]
struct Panes(Mutex<HashMap<String, (isize, PaneKind)>>);

/// The bottom edge each pane that grows upwards (the stack) was opened with, physical px.
#[derive(Default)]
struct Bottoms(Mutex<HashMap<String, i32>>);

/// When this process started, for the startup-time measurement.
struct Started(Instant);

/// Where the tray icon was last clicked (physical px): the tray menu pane opens next to it.
#[derive(Default)]
struct TrayClick(Mutex<Option<(i32, i32)>>);

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
    let (anchor, flipped, dropped) = {
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
        (anchor, anchor != p.prefs.anchor, p.prefs.dropped)
    };
    // Where the owner dropped it, unless smart placement moved it off the text caret.
    let (x, y, w, h) = match dropped {
        Some(f) if !flipped => placement::dropped_rect(area, scale, anchor, f),
        _ => placement::overlay_rect(area, scale, anchor),
    };

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

/// The owner chose where the overlay goes (the tray menu, or a drag with where it was dropped):
/// remember it and move there.
fn choose_anchor(app: &AppHandle, anchor: Anchor, dropped: Option<(f64, f64)>) {
    {
        let state = app.state::<Placement>();
        let mut p = state.0.lock().unwrap();
        p.prefs.anchor = anchor;
        p.prefs.dropped = dropped;
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
            // It stays where it was dropped (owner checks 2026-10-28: snapping to a corner moved
            // the card out from under the pointer, and it faded); the nearest anchor still says
            // which way cards grow and where the other windows go.
            Some(area) => {
                let (x, y) = (origin.0 + last.0 - start.0, origin.1 + last.1 - start.1);
                choose_anchor(&app, placement::nearest_anchor(area, last), Some(placement::to_fraction(area, (x, y))));
            }
            None => place_on_main(&app, Place::Smart),
        }
    });
    Ok(())
}

/// Where the overlay is now, for the frontend's layout at startup.
/// A card comes back without a hotkey (a held card after unlocking, ADR-014 §4): make sure the
/// overlay is shown and topmost again where it was, since locking the screen can leave it hidden
/// or behind other windows (owner check 14, 2026-10-27).
#[tauri::command]
async fn reveal(app: AppHandle) -> Result<(), String> {
    place_on_main(&app, Place::Smart);
    Ok(())
}

/// Swift heard its name, or a card or question came: the overlay and its panes go on top again
/// where they are, without moving or taking focus. A hotkey raises it by placing it; "Hey Swift"
/// had nothing, so another topmost window could cover it (owner checks, 2026-11-09).
#[tauri::command]
async fn raise(app: AppHandle) -> Result<(), String> {
    let main = app.get_webview_window("overlay").ok_or("no overlay window")?;
    win::reshow(main.hwnd().map_err(|e| e.to_string())?.0 as isize);
    for (hwnd, _) in app.state::<Panes>().0.lock().unwrap().values() {
        win::reshow(*hwnd);
    }
    Ok(())
}

/// The work area and scale of the monitor under a point (physical px), or the primary one.
fn area_at(window: &WebviewWindow, point: Option<(i32, i32)>) -> Option<(placement::Area, f64)> {
    let monitor = point
        .and_then(|(x, y)| window.monitor_from_point(x as f64, y as f64).ok().flatten())
        .or_else(|| window.primary_monitor().ok().flatten())?;
    let wa = monitor.work_area();
    Some((placement::Area { x: wa.position.x, y: wa.position.y, w: wa.size.width, h: wa.size.height }, monitor.scale_factor()))
}

/// A pane window (ADR-015 §3): `label` "pane-…", `kind` as in `PaneKind::from_id`, `index` its place
/// among panes of its kind, size in CSS px until it measures itself (`fit_pane`). Already open:
/// left where it is, so nothing moves under the owner's eyes.
#[tauri::command]
async fn open_pane(
    app: AppHandle, label: String, kind: String, index: u32, w: f64, h: f64, card: Option<(f64, f64)>,
) -> Result<(), String> {
    let kind = PaneKind::from_id(&kind).ok_or("unknown pane kind")?;
    if !label.starts_with("pane-") || !label.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return Err("bad pane label".into());
    }
    if app.state::<Panes>().0.lock().unwrap().contains_key(&label) || app.get_webview_window(&label).is_some() {
        return Ok(());
    }
    let main = app.get_webview_window("overlay").ok_or("no overlay window")?;
    let (area, scale) = area_at(&main, win::cursor_pos()).ok_or("no monitor")?;
    let size = ((w * scale).round() as i32, ((h * scale).round() as i32).min(panes::max_height(area)));
    let (anchor, remembered) = {
        let state = app.state::<Placement>();
        let p = state.0.lock().unwrap();
        (p.current, remembered_place(&p.prefs.panes, kind))
    };
    let (x, y) = match remembered {
        _ if kind == PaneKind::Tray => panes::tray_origin(area, scale, *app.state::<TrayClick>().0.lock().unwrap(), size),
        // The stack remembers its bottom edge: it grows upwards.
        Some(f) if kind.grows_up() => {
            let (x, bottom) = panes::remembered_origin(area, scale, f, index, (size.0, 0));
            panes::clamp(area, (x, bottom - size.1), size)
        }
        Some(f) => panes::remembered_origin(area, scale, f, index, size),
        None => panes::default_origin(area, scale, anchor, kind, index, size),
    };
    let typing = kind == PaneKind::Type;
    // The text box never opens over the card on screen (`card`: its top and bottom in the overlay, CSS px).
    let (x, y) = match (typing, card, main.inner_position()) {
        (true, Some((top, bottom)), Ok(at)) => {
            let s = main.scale_factor().unwrap_or(scale);
            let span = (at.y + (top * s).round() as i32, at.y + (bottom * s).round() as i32);
            let below = app.state::<Placement>().0.lock().unwrap().current.is_top();
            panes::clear_of(area, (x, y), size, span, (panes::GAP * scale).round() as i32, below)
        }
        _ => (x, y),
    };
    // Created shown and unfocused (tao shows it with SW_SHOWNOACTIVATE), as the main window;
    // the text box is created focused, since typing is what it's for.
    let window = WebviewWindowBuilder::new(&app, &label, WebviewUrl::App("index.html".into()))
        .title("Swift")
        .transparent(true)
        .decorations(false)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(typing)
        .resizable(false)
        .inner_size(w, h)
        .position(x as f64 / scale, y as f64 / scale)
        .visible(true)
        .build()
        .map_err(|e| e.to_string())?;
    let hwnd = window.hwnd().map_err(|e| e.to_string())?.0 as isize;
    let excluded = if typing { win::init_typing(hwnd) } else { win::init_pane(hwnd) };
    if !excluded {
        eprintln!("warning: pane {label}: capture exclusion failed");
    }
    win::place(hwnd, x, y, size.0, size.1);
    if kind.grows_up() {
        app.state::<Bottoms>().0.lock().unwrap().insert(label.clone(), y + size.1);
    }
    app.state::<Panes>().0.lock().unwrap().insert(label, (hwnd, kind));
    if typing {
        // Opened by a hotkey or the tray menu, so Windows lets Swift take the foreground.
        let _ = window.set_focus();
    }
    Ok(())
}

#[tauri::command]
async fn close_pane(app: AppHandle, label: String) -> Result<(), String> {
    app.state::<Panes>().0.lock().unwrap().remove(&label);
    app.state::<Bottoms>().0.lock().unwrap().remove(&label);
    if let Some(window) = app.get_webview_window(&label) {
        window.destroy().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// The pane measured what it shows (CSS px): the window takes that size, kept on screen.
#[tauri::command]
async fn fit_pane(app: AppHandle, label: String, w: f64, h: f64) -> Result<(), String> {
    let Some((hwnd, _)) = app.state::<Panes>().0.lock().unwrap().get(&label).copied() else {
        return Ok(());
    };
    let window = app.get_webview_window(&label).ok_or("no such pane")?;
    let Some((x, y, _, _)) = win::window_rect(hwnd) else { return Ok(()) };
    let (area, scale) = area_at(&window, Some((x, y))).ok_or("no monitor")?;
    let size = ((w.max(40.0) * scale).round() as i32, ((h.max(24.0) * scale).round() as i32).min(panes::max_height(area)));
    let kind = app.state::<Panes>().0.lock().unwrap().get(&label).map(|(_, k)| *k);
    // The stack keeps the bottom edge it was opened with: expanded, it grows upwards.
    let (_, _, _, old_h) = win::window_rect(hwnd).unwrap_or((x, y, 0, size.1));
    let bottom = app.state::<Bottoms>().0.lock().unwrap().get(&label).copied();
    win::set_size(hwnd, size.0, size.1);
    let (cx, cy) = if kind.is_some_and(PaneKind::grows_up) {
        panes::grown_up(area, x, bottom.unwrap_or(y + old_h), size)
    } else {
        panes::clamp(area, (x, y), size)
    };
    if (cx, cy) != win::window_rect(hwnd).map(|r| (r.0, r.1)).unwrap_or((x, y)) {
        win::move_to(hwnd, cx, cy);
    }
    Ok(())
}

/// Pointer pressed on a pane: follow the cursor while the button is held, anywhere (no snapping),
/// and remember where this kind of pane goes. Returns whether it moved (no: it was a click).
#[tauri::command]
async fn drag_pane(app: AppHandle, label: String) -> Result<bool, String> {
    let Some((hwnd, kind)) = app.state::<Panes>().0.lock().unwrap().get(&label).copied() else {
        return Ok(false);
    };
    if kind == PaneKind::Stack {
        return Ok(false);  // it keeps its corner: a press is only ever a click
    }
    let (Some(start), Some((ox, oy, _, _))) = (win::cursor_pos(), win::window_rect(hwnd)) else {
        return Ok(false);
    };
    let moved = tauri::async_runtime::spawn_blocking(move || {
        let mut moved = false;
        let mut last = start;
        while win::left_button_down() {
            if let Some(c) = win::cursor_pos() {
                let (dx, dy) = (c.0 - start.0, c.1 - start.1);
                if moved || dx.abs() + dy.abs() >= 4 {
                    moved = true;
                    if c != last {
                        win::move_to(hwnd, ox + dx, oy + dy);
                    }
                }
                last = c;
            }
            std::thread::sleep(std::time::Duration::from_millis(8));
        }
        moved
    })
    .await
    .map_err(|e| e.to_string())?;
    if !moved {
        return Ok(false);
    }
    // Shown and on top where it was dropped, as the main window is after its drag (check 19,
    // 2026-10-27: a dragged pane vanished when the mouse was released).
    win::reshow(hwnd);
    let window = app.get_webview_window(&label).ok_or("no such pane")?;
    let Some((x, y, w, h)) = win::window_rect(hwnd) else { return Ok(true) };
    let Some((area, _)) = area_at(&window, Some((x + w / 2, y + h / 2))) else { return Ok(true) };
    let (cx, cy) = panes::clamp(area, (x, y), (w, h));
    if (cx, cy) != (x, y) {
        win::move_to(hwnd, cx, cy);
    }
    let state = app.state::<Placement>();
    let mut p = state.0.lock().unwrap();
    let place = Some(panes::to_fraction(area, (cx, cy)));
    let places = &mut p.prefs.panes;
    match kind {
        PaneKind::Reader => places.reader = place,
        PaneKind::Stack => return Ok(true),  // never remembered: it keeps its corner
        PaneKind::Type => places.typing = place,
        PaneKind::Live => places.live = place,
        PaneKind::Tray => return Ok(true),  // it opens by the tray icon each time
    }
    prefs::save(&p.prefs);
    Ok(true)
}

fn remembered_place(places: &prefs::PanePlaces, kind: PaneKind) -> Option<(f64, f64)> {
    match kind {
        PaneKind::Reader => places.reader,
        // Always its corner, even with a place saved from before (`panes::side`).
        PaneKind::Stack => None,
        PaneKind::Type => places.typing,
        PaneKind::Live => places.live,
        PaneKind::Tray => None,
    }
}

/// The expanded stack folds up on a press anywhere outside it (the owner's design). Resolves
/// true on such a press, false when the pane closed first. Panes never take focus, so this
/// watches the mouse instead of waiting for a blur.
#[tauri::command]
async fn watch_outside(app: AppHandle, label: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut was_down = win::left_button_down();
        loop {
            let Some((hwnd, _)) = app.state::<Panes>().0.lock().unwrap().get(&label).copied() else {
                return false;
            };
            let down = win::left_button_down();
            if down && !was_down {
                let inside = match (win::cursor_pos(), win::window_rect(hwnd)) {
                    (Some((cx, cy)), Some((x, y, w, h))) => cx >= x && cx < x + w && cy >= y && cy < y + h,
                    _ => true,
                };
                if !inside {
                    return true;
                }
            }
            was_down = down;
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
    })
    .await
    .map_err(|e| e.to_string())
}

/// Every pane window open now, so the main window can close one it no longer wants (one
/// left over from an older shell, or a lost close: bug 1 of 2026-10-27).
#[tauri::command]
async fn pane_labels(app: AppHandle) -> Result<Vec<String>, String> {
    let mut labels: Vec<String> = app.webview_windows().into_keys().filter(|l| l.starts_with("pane-")).collect();
    labels.sort();
    Ok(labels)
}

#[tauri::command]
async fn get_placement(placement: State<'_, Placement>) -> Result<PlacementEvent, String> {
    let p = placement.0.lock().unwrap();
    Ok(PlacementEvent { anchor: p.current.id(), flipped: p.current != p.prefs.anchor })
}

/// Whether Windows apps use the light theme (ADR-017); null when Windows doesn't say.
#[tauri::command]
async fn get_theme() -> Result<Option<bool>, String> {
    Ok(theme::apps_use_light())
}

#[derive(Serialize)]
struct TrayPrefs {
    anchor: &'static str,
    smart: bool,
}

/// The tray menu's Position and smart placement (ADR-017).
#[tauri::command]
async fn get_prefs(placement: State<'_, Placement>) -> Result<TrayPrefs, String> {
    let p = placement.0.lock().unwrap();
    Ok(TrayPrefs { anchor: p.prefs.anchor.id(), smart: p.prefs.smart })
}

/// The tray menu's anchor picker: the same as the native menu's Position items.
#[tauri::command]
async fn set_anchor(app: AppHandle, anchor: String) -> Result<(), String> {
    let anchor = Anchor::from_id(&anchor).ok_or("unknown anchor")?;
    choose_anchor(&app, anchor, None);
    Ok(())
}

/// The tray menu's smart placement switch.
#[tauri::command]
async fn set_smart(app: AppHandle, on: bool) -> Result<(), String> {
    {
        let state = app.state::<Placement>();
        let mut p = state.0.lock().unwrap();
        p.prefs.smart = on;
        prefs::save(&p.prefs);
    }
    sync_tray(&app);
    Ok(())
}

/// The tray menu's Settings: config.yaml in its default app (Swift itself never writes it).
#[tauri::command]
async fn open_settings() -> Result<(), String> {
    open_config();
    Ok(())
}

/// The tray menu's (and a stopped engine's card's) Restart Swift.
#[tauri::command]
async fn restart_backend(app: AppHandle) -> Result<(), String> {
    restart_swift(&app);
    Ok(())
}

/// The tray menu's Quit Swift.
#[tauri::command]
async fn quit_app(app: AppHandle) -> Result<(), String> {
    quit(&app);
    Ok(())
}

/// "Copy" on a result card.
#[tauri::command]
async fn copy_text(text: String) -> Result<(), String> {
    win::copy_text(&text)
}

/// A source in a live view (ADR-017 §7): the page in the owner's browser. Only a plain http(s)
/// address: nothing that could run a program or open a file.
#[tauri::command]
async fn open_link(url: String) -> Result<(), String> {
    let url = panes::web_link(&url).ok_or("not a web address")?;
    std::process::Command::new("rundll32.exe")
        .args(["url.dll,FileProtocolHandler", url])
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
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

fn open_config() {
    let path = backend::config_path();
    let _ = std::process::Command::new("explorer.exe").arg(path).spawn();
}

/// Restart Swift without quitting (audit 2026-10, B-04): the backend and everything it started
/// end first (`backend::restart`), off the UI thread; one restart at a time. The overlay
/// reconnects to the new backend by itself.
fn restart_swift(app: &AppHandle) {
    static RESTARTING: AtomicBool = AtomicBool::new(false);
    if RESTARTING.swap(true, Ordering::SeqCst) {
        return;
    }
    let app = app.clone();
    let _ = app.emit_to("overlay", "backend-restarting", ());
    std::thread::spawn(move || {
        let shared = app.state::<SharedBackend>().inner().clone();
        if let Err(problem) = backend::restart(&app, shared) {
            eprintln!("[overlay] restart refused: {problem}");
            let _ = app.emit_to("overlay", "backend-restart-failed", problem);
        }
        RESTARTING.store(false, Ordering::SeqCst);
    });
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
        .manage(Panes::default())
        .manage(Bottoms::default())
        .manage(Placement(Mutex::new({
            let prefs = prefs::load();
            PlacementState { prefs, current: prefs.anchor, ..Default::default() }
        })))
        .manage(started)
        .manage(TrayClick::default())
        .invoke_handler(tauri::generate_handler![
            backend_info,
            register_hotkeys,
            set_escape,
            set_hit_regions,
            overlay_ready,
            diagnostics,
            begin_drag,
            get_placement,
            reveal,
            raise,
            open_pane,
            close_pane,
            fit_pane,
            drag_pane,
            watch_outside,
            pane_labels,
            copy_text,
            open_link,
            open_logs,
            set_status,
            get_theme,
            get_prefs,
            set_anchor,
            set_smart,
            open_settings,
            restart_backend,
            quit_app
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
            // ADR-015 §10: the same as hotkeys.type, for when the shortcut isn't to hand.
            let type_item = MenuItem::with_id(app, "type", "Type to Swift…", true, None::<&str>)?;
            // ADR-017: the same as the tray menu pane's (the overlay knows whether it's paused).
            let pause_item = MenuItem::with_id(app, "pause", "Pause or resume listening", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "Settings (config.yaml)", true, None::<&str>)?;
            let logs_item = MenuItem::with_id(app, "logs", "Open logs folder", true, None::<&str>)?;
            // Audit 2026-10, B-06: saved recordings, used and wiped on this PC only.
            let improve_item = MenuItem::with_id(app, "improve", "Improve speech recognition", true, None::<&str>)?;
            let clear_item = MenuItem::with_id(app, "clear-recordings", "Clear saved recordings", true, None::<&str>)?;
            // Audit 2026-10, B-04: when the engine died or hangs, without quitting.
            let restart_item = MenuItem::with_id(app, "restart", "Restart Swift", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Swift", true, None::<&str>)?;
            let separator2 = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(
                app,
                &[&pause_item, &type_item, &position, &settings_item, &logs_item, &improve_item, &clear_item, &separator2,
                  &restart_item, &quit_item],
            )?;
            app.manage(TrayItems { anchors, smart });
            let mut tray = TrayIconBuilder::with_id("swift")
                .tooltip("Swift: starting")
                .menu(&menu)
                // ADR-017: a left click opens the tray menu pane; the native menu is on the right click.
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, position, .. } = event {
                        let app = tray.app_handle();
                        *app.state::<TrayClick>().0.lock().unwrap() = Some((position.x.round() as i32, position.y.round() as i32));
                        let _ = app.emit_to("overlay", "tray-open", ());
                    }
                })
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "logs" => open_logs_folder(),
                    "settings" => open_config(),
                    "pause" => {
                        let _ = app.emit_to("overlay", "tray-action", "pause");
                    }
                    "improve" | "clear-recordings" => {
                        let _ = app.emit_to("overlay", "tray-action", event.id.as_ref());
                    }
                    "type" => {
                        let _ = app.emit("hotkey", HotkeyEvent { name: "type".into(), state: "down" });
                    }
                    "restart" => restart_swift(app),
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
                            choose_anchor(app, anchor, None);
                        }
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            backend::start(app.handle(), shared_backend.clone());
            theme::watch(app.handle().clone());
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

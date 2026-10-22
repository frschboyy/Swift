//! Click-through control (PLAN.md §5).
//!
//! The overlay ignores the mouse by default. The frontend reports the rects of
//! its interactive elements (CSS px, relative to the window). While that list
//! is non-empty, a thread polls the cursor every 33 ms and lets the mouse in
//! only while it is over one of them. With no rects, the thread sleeps.

use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Emitter, WebviewWindow};

use crate::win;

#[derive(Clone, Copy, Debug, Deserialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

#[derive(Clone, Copy, Default)]
pub struct Geometry {
    pub x: i32,
    pub y: i32,
    pub scale: f64,
}

#[derive(Default)]
pub struct HitState {
    pub rects: Vec<Rect>,
    pub geometry: Geometry,
}

pub type SharedHit = Arc<(Mutex<HitState>, Condvar)>;

#[derive(Clone, Serialize)]
struct HoverEvent {
    inside: bool,
}

fn inside(state: &HitState, cursor: (i32, i32)) -> bool {
    let g = state.geometry;
    if g.scale <= 0.0 {
        return false;
    }
    let cx = (cursor.0 - g.x) as f64 / g.scale;
    let cy = (cursor.1 - g.y) as f64 / g.scale;
    state
        .rects
        .iter()
        .any(|r| cx >= r.x && cx < r.x + r.w && cy >= r.y && cy < r.y + r.h)
}

pub fn spawn(window: WebviewWindow, hwnd: isize, shared: SharedHit) {
    win::set_click_through(hwnd, true);
    std::thread::spawn(move || {
        let (lock, cvar) = &*shared;
        let mut over = false;
        loop {
            // Decide under the lock, act outside it: the style change is a
            // cross-thread SendMessage to the main thread, which may want this lock.
            let now = {
                let state = lock.lock().unwrap();
                if state.rects.is_empty() && !over {
                    let _idle = cvar.wait_while(state, |s| s.rects.is_empty()).unwrap();
                    continue;
                }
                !state.rects.is_empty() && win::cursor_pos().is_some_and(|c| inside(&state, c))
            };
            if now != over {
                over = now;
                win::set_click_through(hwnd, !now);
                if cfg!(debug_assertions) {
                    eprintln!("[overlay] pointer {}", if now { "over a card: clickable" } else { "left: click-through" });
                }
                let _ = window.emit("hover", HoverEvent { inside: now });
            }
            std::thread::sleep(Duration::from_millis(33));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(scale: f64) -> HitState {
        HitState {
            rects: vec![Rect { x: 100.0, y: 50.0, w: 200.0, h: 40.0 }],
            geometry: Geometry { x: 1000, y: 500, scale },
        }
    }

    #[test]
    fn hit_test_respects_window_origin_and_scale() {
        let s = state(1.5);
        // CSS (150, 60) -> physical (1000 + 225, 500 + 90)
        assert!(inside(&s, (1225, 590)));
        assert!(!inside(&s, (1000 + 140, 590))); // CSS x = 93, left of the rect
        assert!(!inside(&s, (1225, 500 + 136))); // CSS y = 90.7, below the rect
    }

    #[test]
    fn zero_scale_never_hits() {
        assert!(!inside(&state(0.0), (1225, 590)));
    }
}

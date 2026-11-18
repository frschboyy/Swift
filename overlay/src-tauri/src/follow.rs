//! A13 (Explore, off by default): the orb follows the monitor the owner is working on.
//!
//! Once the cursor has stayed on another monitor for 1.5 s, the orb fades out (120 ms), is placed where it
//! goes on that monitor (the same anchor, by the hotkey's own placement: never activating, never a click),
//! and fades in (120 ms). Never while a card or an OK is up (the overlay says so), never while Swift is
//! busy or being dragged, never with one monitor, never when the front window is full screen. `Tracker` is
//! pure so the rules are tested here without a second monitor; `spawn` is the thread that feeds it.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::win;

pub const DWELL_MS: u64 = 1500;
pub const FADE_MS: u64 = 120;
const POLL_MS: u64 = 250;

/// A monitor, by the top-left of its area.
pub type Mon = (i32, i32);

pub struct Frame {
    pub now_ms: u64,
    pub monitors: usize,
    pub cursor: Mon,
    pub orb: Mon,
    /// No card, no OK, nothing running or dragged.
    pub idle: bool,
    pub fullscreen: bool,
}

#[derive(Default)]
pub struct Tracker {
    since: Option<(Mon, u64)>,
}

impl Tracker {
    /// True once, when the orb should cross to the cursor's monitor.
    pub fn step(&mut self, f: &Frame) -> bool {
        if f.monitors < 2 || f.cursor == f.orb || !f.idle || f.fullscreen {
            self.since = None;
            return false;
        }
        match self.since {
            Some((m, at)) if m == f.cursor => {
                if f.now_ms.saturating_sub(at) >= DWELL_MS {
                    self.since = None;
                    return true;
                }
                false
            }
            _ => {
                self.since = Some((f.cursor, f.now_ms));
                false
            }
        }
    }
}

/// What the overlay last said: following is on (`explore.follow_monitor`), and nothing is up.
#[derive(Default)]
pub struct FollowState {
    pub on: bool,
    pub idle: bool,
}

pub type Shared = Arc<Mutex<FollowState>>;

#[derive(Clone, Serialize)]
struct FadeEvent {
    /// "out" then "in"; the overlay fades its orb (120 ms each way, none with reduced motion).
    phase: &'static str,
}

pub fn spawn(app: AppHandle, shared: Shared) {
    std::thread::spawn(move || {
        let start = Instant::now();
        let mut tracker = Tracker::default();
        loop {
            std::thread::sleep(Duration::from_millis(POLL_MS));
            let (on, idle) = {
                let s = shared.lock().unwrap();
                (s.on, s.idle)
            };
            if !on {
                tracker = Tracker::default();
                continue;
            }
            let Some(frame) = crate::follow_frame(&app, start.elapsed().as_millis() as u64, idle) else {
                continue;
            };
            if tracker.step(&frame) {
                let _ = app.emit("follow", FadeEvent { phase: "out" });
                std::thread::sleep(Duration::from_millis(FADE_MS));
                crate::place_on_main(&app, crate::Place::Smart);
                std::thread::sleep(Duration::from_millis(60));
                let _ = app.emit("follow", FadeEvent { phase: "in" });
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(now_ms: u64) -> Frame {
        Frame { now_ms, monitors: 2, cursor: (1920, 0), orb: (0, 0), idle: true, fullscreen: false }
    }

    #[test]
    fn crosses_after_one_and_a_half_seconds_on_the_other_monitor() {
        let mut t = Tracker::default();
        assert!(!t.step(&frame(0)));
        assert!(!t.step(&frame(1499)));
        assert!(t.step(&frame(1500)));
        assert!(!t.step(&frame(1600)), "fires once, then waits again");
    }

    #[test]
    fn going_back_or_a_third_monitor_restarts_the_wait() {
        let mut t = Tracker::default();
        t.step(&frame(0));
        assert!(!t.step(&Frame { cursor: (0, 0), ..frame(1000) }));
        assert!(!t.step(&frame(2000)));
        assert!(!t.step(&Frame { cursor: (3840, 0), ..frame(3000) }));
        assert!(!t.step(&Frame { cursor: (3840, 0), ..frame(4400) }));
        assert!(t.step(&Frame { cursor: (3840, 0), ..frame(4500) }));
    }

    #[test]
    fn never_with_a_card_one_monitor_or_full_screen() {
        for blocked in [
            Frame { idle: false, ..frame(0) },
            Frame { monitors: 1, ..frame(0) },
            Frame { fullscreen: true, ..frame(0) },
        ] {
            let mut t = Tracker::default();
            t.step(&blocked);
            assert!(!t.step(&Frame { idle: blocked.idle, monitors: blocked.monitors, fullscreen: blocked.fullscreen, ..frame(5000) }));
        }
    }

    #[test]
    fn a_card_in_the_middle_of_the_wait_restarts_it() {
        let mut t = Tracker::default();
        t.step(&frame(0));
        t.step(&Frame { idle: false, ..frame(1000) });
        assert!(!t.step(&frame(1600)));
        assert!(t.step(&frame(3100)));
    }
}

//! The overlay page stopped talking to the backend and never came back (owner, 2026-11-17: after a
//! sleep the page dropped its socket at 11:34 and stayed silent until a restart at 14:28; cause
//! unproven). The page reports `overlay_alive` while connected; when the backend is up and the
//! page has been silent for `MISSES` checks in a row, Rust (which outlives the page) reloads it.
//! Checks are counted, not timed, so a sleep alone never triggers a reload.

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use tauri::{AppHandle, Manager};

use crate::backend::SharedBackend;

const CHECK: Duration = Duration::from_secs(15);
const MISSES: u32 = 4;

/// Set by the page while it is connected; cleared by each check.
#[derive(Default)]
pub struct Alive(pub AtomicBool);

#[tauri::command]
pub async fn overlay_alive(alive: tauri::State<'_, Alive>) -> Result<(), String> {
    alive.0.store(true, Ordering::SeqCst);
    Ok(())
}

/// One check: the misses so far, and whether to reload now.
fn check(seen: bool, backend_up: bool, misses: u32) -> (u32, bool) {
    if seen || !backend_up {
        return (0, false); // a backend that's starting or failed is the page's to report, not a silence
    }
    if misses + 1 >= MISSES {
        (0, true)
    } else {
        (misses + 1, false)
    }
}

pub fn spawn(app: AppHandle) {
    std::thread::spawn(move || {
        let mut misses = 0;
        loop {
            std::thread::sleep(CHECK);
            let seen = app.state::<Alive>().0.swap(false, Ordering::SeqCst);
            let up = app.state::<SharedBackend>().lock().unwrap().info.is_some();
            let reload;
            (misses, reload) = check(seen, up, misses);
            if reload {
                eprintln!("[overlay] page silent for {MISSES} checks with the backend up: reloading it");
                if let Some(window) = app.get_webview_window("overlay") {
                    let _ = window.reload();
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reloads_after_four_silent_checks_with_the_backend_up() {
        let mut m = 0;
        for _ in 0..3 {
            let (next, reload) = check(false, true, m);
            assert!(!reload);
            m = next;
        }
        assert_eq!(check(false, true, m), (0, true));
    }

    #[test]
    fn a_report_or_a_backend_down_resets_the_count() {
        assert_eq!(check(true, true, 3), (0, false));
        assert_eq!(check(false, false, 3), (0, false));
    }
}

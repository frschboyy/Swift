//! Dark or light (ADR-017, the Capsule redesign): the overlay follows Windows' app theme.
//!
//! `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme` is a
//! DWORD, 1 for light apps and 0 for dark (missing on old builds: dark). `get_theme` reads it at
//! start; `watch` waits on the key (`RegNotifyChangeKeyValue`, no polling) and tells every window
//! (`theme`, the new value) whenever Windows changes it, so the overlay switches live.

use tauri::{AppHandle, Emitter};
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::System::Registry::{
    RegCloseKey, RegGetValueW, RegNotifyChangeKeyValue, RegOpenKeyExW, HKEY, HKEY_CURRENT_USER, KEY_NOTIFY,
    KEY_QUERY_VALUE, REG_NOTIFY_CHANGE_LAST_SET, RRF_RT_REG_DWORD,
};

const KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize";
const VALUE: &str = "AppsUseLightTheme";

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// The registry's DWORD as "light apps?": anything but 0 is light; missing is unknown.
pub fn light_from(value: Option<u32>) -> Option<bool> {
    value.map(|v| v != 0)
}

/// Whether Windows apps use the light theme now (None: the value isn't there).
pub fn apps_use_light() -> Option<bool> {
    let (key, value) = (wide(KEY), wide(VALUE));
    let mut data: u32 = 0;
    let mut size = std::mem::size_of::<u32>() as u32;
    // SAFETY: valid NUL-terminated strings and a DWORD-sized buffer with its size.
    let status = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            key.as_ptr(),
            value.as_ptr(),
            RRF_RT_REG_DWORD,
            std::ptr::null_mut(),
            (&mut data as *mut u32).cast(),
            &mut size,
        )
    };
    light_from((status == ERROR_SUCCESS).then_some(data))
}

/// Tell every window when the app theme changes. Runs on its own thread for the app's lifetime.
pub fn watch(app: AppHandle) {
    std::thread::spawn(move || {
        let key = wide(KEY);
        let mut hkey: HKEY = std::ptr::null_mut();
        // SAFETY: a valid subkey string; `hkey` receives the opened key.
        let opened = unsafe { RegOpenKeyExW(HKEY_CURRENT_USER, key.as_ptr(), 0, KEY_NOTIFY | KEY_QUERY_VALUE, &mut hkey) };
        if opened != ERROR_SUCCESS {
            eprintln!("[overlay] theme: can't watch the Personalize key ({opened})");
            return;
        }
        let mut last = apps_use_light();
        loop {
            // SAFETY: an open key; synchronous wait, no event handle.
            let status = unsafe { RegNotifyChangeKeyValue(hkey, 0, REG_NOTIFY_CHANGE_LAST_SET, std::ptr::null_mut(), 0) };
            if status != ERROR_SUCCESS {
                eprintln!("[overlay] theme: watching stopped ({status})");
                break;
            }
            let now = apps_use_light();
            if now != last {
                last = now;
                eprintln!("[overlay] theme: {}", if now == Some(true) { "light" } else { "dark" });
                let _ = app.emit("theme", now);
            }
        }
        // SAFETY: the key opened above.
        unsafe { RegCloseKey(hkey) };
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_dword_reads_as_light_or_dark() {
        assert_eq!(light_from(Some(1)), Some(true));
        assert_eq!(light_from(Some(0)), Some(false));
        assert_eq!(light_from(None), None);
    }

    #[test]
    fn this_machine_answers_or_says_it_does_not_know() {
        // Whatever the theme is, reading it never fails loudly.
        let _ = apps_use_light();
    }
}

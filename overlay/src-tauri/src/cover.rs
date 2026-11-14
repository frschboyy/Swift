//! Windows Swift can't come in front of (A10, owner checks 203 and 254).
//!
//! Windows keeps windows in z-order bands. Every ordinary app, Swift included, is in the desktop
//! band (1), where Swift's `raise` (HWND_TOPMOST, no focus taken) puts it in front of any other
//! always-on-top window. A few system binaries create their windows in a higher band: Task Manager
//! with Options > Always on top is in band 16 ("system tools", check 254 on the owner's PC), and
//! nothing in band 1 can go above it short of a signed UI-access install, which the owner declined
//! (2026-11-14). So Swift moves out from under such a window instead: this lists where they are.
//!
//! The band comes from `GetWindowBand` (user32, undocumented, the same call as
//! `spikes/desktop/window_bands.py`); without it, nothing is reported and Swift stays put.
//! Counted: visible, not minimised, not cloaked (a hidden Start menu or search panel is cloaked),
//! always on top, not click-through, not Swift's own, in a band above Swift's. Only rects, bands
//! and executable names are read, never titles or anything inside a window.
//!
//! Run when a card is about to show (`raise`) or the overlay is placed: never polled.

use std::ffi::c_void;

use windows_sys::Win32::Foundation::{BOOL, CloseHandle, HWND, LPARAM, RECT};
use windows_sys::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS};
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
use windows_sys::Win32::System::Threading::{
    GetCurrentProcessId, OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindowLongPtrW, GetWindowRect, GetWindowThreadProcessId, IsIconic, IsWindowVisible, GWL_EXSTYLE,
    WS_EX_TOPMOST, WS_EX_TRANSPARENT,
};

use crate::placement::Rect;

/// A window in a higher band than Swift's, for the decision and the log (no title).
#[derive(Clone, Debug)]
pub struct Cover {
    pub rect: Rect,
    pub band: u32,
    pub exe: String,
}

type GetWindowBand = unsafe extern "system" fn(HWND, *mut u32) -> BOOL;

fn get_window_band() -> Option<GetWindowBand> {
    let user32: Vec<u16> = "user32.dll\0".encode_utf16().collect();
    unsafe {
        let module = GetModuleHandleW(user32.as_ptr());
        if module.is_null() {
            return None;
        }
        let f = GetProcAddress(module, b"GetWindowBand\0".as_ptr())?;
        Some(std::mem::transmute::<unsafe extern "system" fn() -> isize, GetWindowBand>(f))
    }
}

fn band_of(f: GetWindowBand, hwnd: HWND) -> Option<u32> {
    let mut band = 0u32;
    (unsafe { f(hwnd, &mut band) } != 0).then_some(band)
}

fn exe_of(pid: u32) -> String {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return "?".into();
        }
        let mut buf = [0u16; 520];
        let mut size = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(handle, 0, buf.as_mut_ptr(), &mut size);
        CloseHandle(handle);
        if ok == 0 {
            return "?".into();
        }
        let path = String::from_utf16_lossy(&buf[..size as usize]);
        path.rsplit('\\').next().unwrap_or("?").to_lowercase()
    }
}

/// The window's visible bounds (without the invisible resize border), else its window rect.
fn bounds(hwnd: HWND) -> Option<Rect> {
    let mut r = RECT { left: 0, top: 0, right: 0, bottom: 0 };
    let size = std::mem::size_of::<RECT>() as u32;
    let ok = unsafe { DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS as u32, &mut r as *mut _ as *mut c_void, size) } == 0
        || unsafe { GetWindowRect(hwnd, &mut r) } != 0;
    (ok && r.right > r.left && r.bottom > r.top).then_some((r.left, r.top, r.right - r.left, r.bottom - r.top))
}

fn cloaked(hwnd: HWND) -> bool {
    let mut value = 0u32;
    let size = std::mem::size_of::<u32>() as u32;
    unsafe { DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED as u32, &mut value as *mut _ as *mut c_void, size) == 0 && value != 0 }
}

struct Walk {
    get_band: GetWindowBand,
    above: u32,
    own_pid: u32,
    found: Vec<Cover>,
}

unsafe extern "system" fn each(hwnd: HWND, data: LPARAM) -> BOOL {
    let walk = &mut *(data as *mut Walk);
    if IsWindowVisible(hwnd) == 0 || IsIconic(hwnd) != 0 {
        return 1;
    }
    let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32;
    if ex & WS_EX_TOPMOST == 0 || ex & WS_EX_TRANSPARENT != 0 {
        return 1;
    }
    let mut pid = 0u32;
    GetWindowThreadProcessId(hwnd, &mut pid);
    if pid == walk.own_pid {
        return 1;
    }
    match band_of(walk.get_band, hwnd) {
        Some(band) if band > walk.above => {
            if cloaked(hwnd) {
                return 1;
            }
            if let Some(rect) = bounds(hwnd) {
                walk.found.push(Cover { rect, band, exe: exe_of(pid) });
            }
        }
        _ => {}
    }
    1
}

/// The always-on-top windows in a higher band than `own` (Swift's overlay window, a raw HWND).
pub fn above(own: isize) -> Vec<Cover> {
    let Some(get_band) = get_window_band() else {
        return Vec::new();
    };
    let Some(above) = band_of(get_band, own as HWND) else {
        return Vec::new();
    };
    let mut walk = Walk { get_band, above, own_pid: unsafe { GetCurrentProcessId() }, found: Vec::new() };
    unsafe { EnumWindows(Some(each), &mut walk as *mut Walk as LPARAM) };
    walk.found
}

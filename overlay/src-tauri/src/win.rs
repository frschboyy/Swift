//! Win32 details Tauri doesn't expose (PLAN.md §5).
//!
//! - `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`: never foreground, no taskbar or Alt+Tab entry.
//! - Click-through: `WS_EX_LAYERED | WS_EX_TRANSPARENT` (the same bits tao uses for
//!   `set_ignore_cursor_events`), toggled here directly and synchronously.
//! - Every extended-style change is corrected in `WM_STYLECHANGING`: tao rewrites the whole
//!   extended style from its own flags (adding `WS_EX_APPWINDOW`, dropping ours) whenever it
//!   applies any window flag, so re-applying afterwards would race with it.
//! - `WM_MOUSEACTIVATE -> MA_NOACTIVATE`: clicking a card button must not activate us,
//!   even though WebView2 hosts its own child windows.
//! - `WDA_EXCLUDEFROMCAPTURE`: invisible to screen capture (Windows 10 2004+).
//! - Placement with `SWP_NOACTIVATE`, so moving between monitors never takes focus.
//! - Smart placement reads the foreground thread's text caret (`GetGUIThreadInfo`);
//!   apps that draw their own caret (most browsers) report none, and nothing moves.
//! - Copy goes through the Win32 clipboard: the overlay never has focus, which the
//!   web Clipboard API requires.
//!
//! Handles are passed around as `isize` because `HWND` is a raw pointer and not `Send`.

use std::sync::atomic::{AtomicBool, Ordering};

use windows_sys::Win32::Foundation::{GlobalFree, HWND, LPARAM, LRESULT, POINT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::ClientToScreen;
use windows_sys::Win32::System::DataExchange::{CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData};
use windows_sys::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{GetAsyncKeyState, VK_LBUTTON};
use windows_sys::Win32::UI::Shell::{DefSubclassProc, SetWindowSubclass};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetCursorPos, GetGUIThreadInfo, GetWindowLongPtrW, SetWindowDisplayAffinity, SetWindowLongPtrW,
    SetWindowPos, ShowWindow, GUITHREADINFO, GWL_EXSTYLE, HWND_TOPMOST, MA_NOACTIVATE, STYLESTRUCT,
    SWP_NOACTIVATE, SWP_NOSIZE, SWP_NOZORDER, SWP_SHOWWINDOW, SW_SHOWNOACTIVATE,
    WDA_EXCLUDEFROMCAPTURE, WM_MOUSEACTIVATE, WM_STYLECHANGING, WS_EX_APPWINDOW, WS_EX_LAYERED,
    WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT,
};

const SUBCLASS_ID: usize = 0x5357_4654; // "SWFT"

/// Desired click-through state; `WM_STYLECHANGING` enforces it.
static CLICK_THROUGH: AtomicBool = AtomicBool::new(true);

fn hwnd(raw: isize) -> HWND {
    raw as HWND
}

/// The extended style Swift requires, given whatever someone else tried to set.
fn enforce(ex: u32) -> u32 {
    let mut ex = (ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST) & !WS_EX_APPWINDOW;
    if CLICK_THROUGH.load(Ordering::SeqCst) {
        ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT;
    } else {
        ex &= !(WS_EX_LAYERED | WS_EX_TRANSPARENT);
    }
    ex
}

/// Re-apply the required extended style (the subclass enforces it on the way in).
pub fn ensure_styles(raw: isize) {
    unsafe {
        let h = hwnd(raw);
        let ex = GetWindowLongPtrW(h, GWL_EXSTYLE);
        let want = enforce(ex as u32) as isize;
        if want != ex {
            SetWindowLongPtrW(h, GWL_EXSTYLE, want);
        }
    }
}

/// Synchronous: the style has changed when this returns.
pub fn set_click_through(raw: isize, through: bool) {
    CLICK_THROUGH.store(through, Ordering::SeqCst);
    ensure_styles(raw);
}

pub fn ex_style(raw: isize) -> isize {
    unsafe { GetWindowLongPtrW(hwnd(raw), GWL_EXSTYLE) }
}

pub fn is_click_through(raw: isize) -> bool {
    ex_style(raw) & WS_EX_TRANSPARENT as isize != 0
}

unsafe extern "system" fn overlay_proc(
    h: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    _id: usize,
    _data: usize,
) -> LRESULT {
    match msg {
        WM_MOUSEACTIVATE => return MA_NOACTIVATE as LRESULT,
        WM_STYLECHANGING if wparam as i32 == GWL_EXSTYLE => {
            let change = lparam as *mut STYLESTRUCT;
            (*change).styleNew = enforce((*change).styleNew);
        }
        _ => {}
    }
    DefSubclassProc(h, msg, wparam, lparam)
}

/// One-time setup. Returns false if capture exclusion failed (e.g. Windows older than 2004).
pub fn init_overlay(raw: isize) -> bool {
    unsafe {
        let h = hwnd(raw);
        SetWindowSubclass(h, Some(overlay_proc), SUBCLASS_ID, 0);
        ensure_styles(raw);
        // Debug builds only: SWIFT_DEV_ALLOW_CAPTURE=1 leaves the overlay capturable so its
        // rendering can be checked with screenshots. Release builds always exclude it.
        if cfg!(debug_assertions) && std::env::var_os("SWIFT_DEV_ALLOW_CAPTURE").is_some() {
            eprintln!("[overlay] SWIFT_DEV_ALLOW_CAPTURE: capture exclusion OFF (debug build)");
            return true;
        }
        SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE) != 0
    }
}

/// Move/resize in physical pixels, topmost, without activating, and make sure it's shown.
pub fn place(raw: isize, x: i32, y: i32, w: i32, h: i32) {
    unsafe {
        let handle = hwnd(raw);
        SetWindowPos(handle, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW);
        ShowWindow(handle, SW_SHOWNOACTIVATE);
    }
}

pub fn cursor_pos() -> Option<(i32, i32)> {
    let mut p = POINT { x: 0, y: 0 };
    let ok = unsafe { GetCursorPos(&mut p) };
    (ok != 0).then_some((p.x, p.y))
}

/// Move without resizing, activating or changing the z-order (dragging a card).
pub fn move_to(raw: isize, x: i32, y: i32) {
    unsafe {
        SetWindowPos(hwnd(raw), std::ptr::null_mut(), x, y, 0, 0, SWP_NOACTIVATE | SWP_NOSIZE | SWP_NOZORDER);
    }
}

/// Whether the (logical) left mouse button is held right now.
pub fn left_button_down() -> bool {
    unsafe { GetAsyncKeyState(VK_LBUTTON as i32) as u16 & 0x8000 != 0 }
}

/// The foreground app's text caret in screen pixels, if it has a system caret.
pub fn caret_pos() -> Option<(i32, i32)> {
    unsafe {
        let mut info: GUITHREADINFO = std::mem::zeroed();
        info.cbSize = std::mem::size_of::<GUITHREADINFO>() as u32;
        if GetGUIThreadInfo(0, &mut info) == 0 || info.hwndCaret.is_null() {
            return None;
        }
        let r = info.rcCaret;
        let mut p = POINT { x: r.left, y: r.bottom };
        (ClientToScreen(info.hwndCaret, &mut p) != 0).then_some((p.x, p.y))
    }
}

const CF_UNICODETEXT: u32 = 13;

/// Put `text` on the clipboard. Doesn't need (or take) focus.
pub fn copy_text(text: &str) -> Result<(), String> {
    let wide: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
    let bytes = wide.len() * std::mem::size_of::<u16>();
    unsafe {
        if OpenClipboard(std::ptr::null_mut()) == 0 {
            return Err("the clipboard is busy".into());
        }
        let result = (|| {
            EmptyClipboard();
            let mem = GlobalAlloc(GMEM_MOVEABLE, bytes);
            if mem.is_null() {
                return Err("out of memory".to_string());
            }
            let dst = GlobalLock(mem) as *mut u16;
            if dst.is_null() {
                GlobalFree(mem);
                return Err("could not lock clipboard memory".to_string());
            }
            std::ptr::copy_nonoverlapping(wide.as_ptr(), dst, wide.len());
            GlobalUnlock(mem);
            // On success the clipboard owns the memory.
            if SetClipboardData(CF_UNICODETEXT, mem as _).is_null() {
                GlobalFree(mem);
                return Err("the clipboard refused the text".to_string());
            }
            Ok(())
        })();
        CloseClipboard();
        result
    }
}

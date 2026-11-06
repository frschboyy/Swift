//! Where pane windows go (ADR-015 §3). Pure, so it can be tested for layouts this machine doesn't have.
//!
//! With no remembered place, a pane goes in free space away from the main window: the waiting stack
//! on the far side from the main window's column, the reader and live views on the other side, so
//! none covers the card in front. Dragged somewhere, a kind remembers where, as a fraction of the
//! work area, so it holds across monitors and resolutions.
//!
//! ADR-015 §9, §10: the waiting stack sits in a bottom corner and grows upwards when it expands. The
//! text box goes where the cards appear, at the main window's anchored edge.

use crate::placement::{card_zone, Anchor, Area, MARGIN};

/// Space between stacked panes, CSS px.
pub const GAP: f64 = 8.0;
/// How far a second live view sits from the first (down and in), CSS px.
pub const CASCADE: f64 = 32.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PaneKind {
    Reader,
    /// The waiting stack (ADR-015 §9).
    Stack,
    /// The text box (ADR-015 §10): the one pane that takes the keyboard.
    Type,
    /// The tray menu (ADR-017): opened by a click on the tray icon, next to it.
    Tray,
    /// A running request's live view (ADR-017 §7): on the reader's side, one per request, cascaded.
    Live,
}

impl PaneKind {
    pub fn from_id(id: &str) -> Option<PaneKind> {
        match id {
            "reader" => Some(PaneKind::Reader),
            "stack" => Some(PaneKind::Stack),
            "type" => Some(PaneKind::Type),
            "tray" => Some(PaneKind::Tray),
            "live" => Some(PaneKind::Live),
            _ => None,
        }
    }

    /// The stack grows upwards from the bottom edge it sits on; the others grow down.
    pub fn grows_up(self) -> bool {
        self == PaneKind::Stack
    }
}

/// Which side of the screen (-1 left, 1 right) a kind goes on, given where the main window is.
fn side(kind: PaneKind, main: Anchor) -> i32 {
    match (kind, main.column()) {
        (PaneKind::Stack | PaneKind::Type, 1) => -1,
        (PaneKind::Stack | PaneKind::Type, _) => 1,
        (PaneKind::Reader | PaneKind::Live, -1) => 1,
        (PaneKind::Reader | PaneKind::Live, _) => -1,
        (PaneKind::Tray, _) => 1,
    }
}

/// Where the tray menu goes: next to the tray icon that was clicked (`click`, physical px), on the
/// side of the screen the taskbar is on; without a click, the bottom-right corner.
pub fn tray_origin(area: Area, scale: f64, click: Option<(i32, i32)>, size: (i32, i32)) -> (i32, i32) {
    let scale = if scale.is_finite() && scale > 0.0 { scale } else { 1.0 };
    let m = (MARGIN * scale).round() as i32;
    let Some((cx, cy)) = click else {
        return clamp(area, (area.x + area.w as i32 - size.0 - m, area.y + area.h as i32 - size.1 - m), size);
    };
    let x = cx - size.0 / 2;
    // The taskbar is outside the work area: above it if the click is below the middle, else under it.
    let y = if cy >= area.y + area.h as i32 / 2 { area.y + area.h as i32 - size.1 - m } else { area.y + m };
    clamp(area, (x, y), size)
}

/// Keep a rect inside the work area.
pub fn clamp(area: Area, (x, y): (i32, i32), (w, h): (i32, i32)) -> (i32, i32) {
    let max_x = area.x + (area.w as i32 - w).max(0);
    let max_y = area.y + (area.h as i32 - h).max(0);
    (x.clamp(area.x, max_x), y.clamp(area.y, max_y))
}

/// The text box moved off the card on screen (`card`: its top and bottom, physical px): under it when
/// the cards come from the top, else over it; the other side when there's no room. Opened from
/// "Change" on a confirm card, the box sat under the card and only showed once the card had gone
/// (owner checks 2026-11-04, 4).
pub fn clear_of(area: Area, (x, y): (i32, i32), (w, h): (i32, i32), (top, bottom): (i32, i32), gap: i32, below: bool) -> (i32, i32) {
    if y + h <= top || y >= bottom {
        return (x, y);
    }
    let under = bottom + gap;
    let over = top - gap - h;
    let fits_under = under + h <= area.y + area.h as i32;
    let fits_over = over >= area.y;
    let y = match (below, fits_under, fits_over) {
        (true, true, _) | (false, true, false) => under,
        (false, _, true) | (true, false, true) => over,
        _ => y,
    };
    clamp(area, (x, y), (w, h))
}

/// Where a pane of `size` (physical px) goes the first time: free space away from the main window.
/// `index` cascades the second and third live view from the first.
pub fn default_origin(area: Area, scale: f64, main: Anchor, kind: PaneKind, index: u32, size: (i32, i32)) -> (i32, i32) {
    let scale = if scale.is_finite() && scale > 0.0 { scale } else { 1.0 };
    let m = (MARGIN * scale).round() as i32;
    if kind == PaneKind::Type {
        // Where the cards appear: the answer shows up right where the request was typed.
        let (zx, zy, zw, zh) = card_zone(area, scale, main);
        let x = zx + (zw - size.0) / 2;
        let y = if main.is_top() { zy } else { zy + zh - size.1 };
        return clamp(area, (x, y), size);
    }
    if kind == PaneKind::Live {
        // Under where the reader opens, a second and third view a step further in and down.
        let shift = (CASCADE * scale).round() as i32 * index as i32;
        let x = if side(kind, main) < 0 { area.x + m + shift } else { area.x + area.w as i32 - size.0 - m - shift };
        return clamp(area, (x, area.y + m + shift), size);
    }
    let x = if side(kind, main) < 0 { area.x + m } else { area.x + area.w as i32 - size.0 - m };
    let y = match kind {
        PaneKind::Reader => area.y + m,
        PaneKind::Stack | PaneKind::Tray => area.y + area.h as i32 - m - size.1,
        PaneKind::Type | PaneKind::Live => unreachable!("placed above"),
    };
    clamp(area, (x, y), size)
}

/// A remembered place (fractions of the work area) back in pixels; the `index`-th of a kind stacks under it.
pub fn remembered_origin(area: Area, scale: f64, (rx, ry): (f64, f64), index: u32, size: (i32, i32)) -> (i32, i32) {
    let scale = if scale.is_finite() && scale > 0.0 { scale } else { 1.0 };
    let step = size.1 + (GAP * scale).round() as i32;
    let x = area.x + (rx.clamp(0.0, 1.0) * area.w as f64).round() as i32;
    let y = area.y + (ry.clamp(0.0, 1.0) * area.h as f64).round() as i32 + step * index as i32;
    clamp(area, (x, y), size)
}

/// Where a pane was dropped, as fractions of the work area (what is remembered).
pub fn to_fraction(area: Area, (x, y): (i32, i32)) -> (f64, f64) {
    (
        ((x - area.x) as f64 / area.w.max(1) as f64).clamp(0.0, 1.0),
        ((y - area.y) as f64 / area.h.max(1) as f64).clamp(0.0, 1.0),
    )
}

/// A live view's source, fit to hand to the browser (ADR-017 §7): http(s) only, a host, no spaces,
/// quotes or control characters (nothing a shell or `url.dll` could read as more than an address).
pub fn web_link(url: &str) -> Option<&str> {
    let url = url.trim();
    let lower = url.to_ascii_lowercase();
    let rest = lower.strip_prefix("https://").or_else(|| lower.strip_prefix("http://"))?;
    let host = rest.split(['/', '?', '#']).next().unwrap_or("");
    let ok = url.len() <= 2048
        && !host.is_empty()
        && !host.starts_with(['.', '-', ':', '@'])
        && url.chars().all(|c| c.is_ascii_graphic() && !matches!(c, '"' | '\'' | '<' | '>' | '`' | '\\' | '^' | '|' | '{' | '}'));
    ok.then_some(url)
}

/// The reader's height at most: 70 % of the work area.
pub fn max_height(area: Area) -> i32 {
    (area.h as f64 * 0.7).round() as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::placement::card_zone;

    const FHD: Area = Area { x: 0, y: 0, w: 1920, h: 1040 };

    #[test]
    fn the_text_box_moves_off_the_card() {
        // Over the card: under it for cards from the top, over it for cards from the bottom.
        assert_eq!(clear_of(FHD, (700, 100), (512, 52), (80, 400), 8, true), (700, 408));
        assert_eq!(clear_of(FHD, (700, 700), (512, 52), (600, 1000), 8, false), (700, 540));
        // Already clear: left where it was.
        assert_eq!(clear_of(FHD, (700, 500), (512, 52), (80, 400), 8, true), (700, 500));
        // No room under a card that fills the bottom: over it instead.
        assert_eq!(clear_of(FHD, (700, 900), (512, 52), (600, 1030), 8, true), (700, 540));
    }
    const SMALL: (i32, i32) = (300, 44);
    const READER: (i32, i32) = (560, 600);

    fn overlaps(a: (i32, i32, i32, i32), b: (i32, i32, i32, i32)) -> bool {
        a.0 < b.0 + b.2 && b.0 < a.0 + a.2 && a.1 < b.1 + b.3 && b.1 < a.1 + a.3
    }

    #[test]
    fn panes_never_cover_the_card_in_front() {
        for main in Anchor::ALL {
            let zone = card_zone(FHD, 1.0, main);
            let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Reader, 0, READER);
            assert!(!overlaps((x, y, READER.0, READER.1), zone), "reader over the card at {main:?}");
        }
    }

    #[test]
    fn remembered_places_round_trip_and_stay_on_screen() {
        let f = to_fraction(FHD, (1200, 300));
        assert_eq!(remembered_origin(FHD, 1.0, f, 0, SMALL), (1200, 300));
        assert_eq!(remembered_origin(FHD, 1.0, f, 1, SMALL), (1200, 352));
        // Remembered on a big monitor, shown on a small one: still inside.
        let small = Area { x: -1280, y: 0, w: 1280, h: 720 };
        let (x, y) = remembered_origin(small, 1.0, (0.99, 0.99), 0, READER);
        assert!(x >= small.x && x + READER.0 <= small.x + small.w as i32);
        assert!(y >= small.y && y + READER.1 <= small.y + small.h as i32);
    }

    #[test]
    fn kinds_parse() {
        assert_eq!(PaneKind::from_id("request"), None);  // ADR-018: other requests are in the main window
        assert_eq!(PaneKind::from_id("reader"), Some(PaneKind::Reader));
        assert_eq!(PaneKind::from_id("stack"), Some(PaneKind::Stack));
        assert_eq!(PaneKind::from_id("type"), Some(PaneKind::Type));
        assert_eq!(PaneKind::from_id("tray"), Some(PaneKind::Tray));
        assert_eq!(PaneKind::from_id("live"), Some(PaneKind::Live));
        assert_eq!(PaneKind::from_id("main"), None);
        assert!(PaneKind::Stack.grows_up() && !PaneKind::Reader.grows_up());
    }

    const STACK: (i32, i32) = (300, 72);

    #[test]
    fn the_stack_sits_in_a_bottom_corner_clear_of_the_card_and_the_reader() {
        for main in Anchor::ALL {
            let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Stack, 0, STACK);
            let stack = (x, y, STACK.0, STACK.1);
            assert_eq!(y + STACK.1, FHD.h as i32 - MARGIN as i32, "{main:?}: not at the bottom");
            assert!(x == MARGIN as i32 || x + STACK.0 == FHD.w as i32 - MARGIN as i32, "{main:?}: not in a corner");
            assert!(!overlaps(stack, card_zone(FHD, 1.0, main)), "stack over the card at {main:?}");
            let (rx, ry) = default_origin(FHD, 1.0, main, PaneKind::Reader, 0, READER);
            assert!(!overlaps(stack, (rx, ry, READER.0, READER.1)), "stack under the reader at {main:?}");
        }
    }

    #[test]
    fn the_tray_menu_opens_by_its_icon_on_the_taskbar_side() {
        let size = (280, 400);
        // Taskbar at the bottom: the menu sits above it, centred on the icon, inside the screen.
        let (x, y) = tray_origin(FHD, 1.0, Some((1800, 1060)), size);
        assert_eq!(y + size.1, FHD.h as i32 - MARGIN as i32);
        assert_eq!(x, FHD.w as i32 - size.0);  // clamped at the right edge
        // Taskbar at the top.
        let top = Area { x: 0, y: 40, w: 1920, h: 1040 };
        let (_, y) = tray_origin(top, 1.0, Some((900, 20)), size);
        assert_eq!(y, 40 + MARGIN as i32);
        // No click known: the bottom-right corner.
        let (x, y) = tray_origin(FHD, 1.0, None, size);
        assert_eq!((x + size.0, y + size.1), (FHD.w as i32 - MARGIN as i32, FHD.h as i32 - MARGIN as i32));
    }

    #[test]
    fn only_web_addresses_go_to_the_browser() {
        assert_eq!(web_link(" https://www.britannica.com/topic/tea "), Some("https://www.britannica.com/topic/tea"));
        assert_eq!(web_link("http://example.com/?q=tea#x"), Some("http://example.com/?q=tea#x"));
        for bad in [
            "file:///C:/Windows/System32/calc.exe", "javascript:alert(1)", "https://", "https:///path", "C:\\x.exe",
            "https://a.example/ x", "https://a.example/\"&calc", "ms-settings:privacy", "https://a.example/\u{7}",
        ] {
            assert_eq!(web_link(bad), None, "{bad}");
        }
        assert_eq!(web_link(&format!("https://a.example/{}", "x".repeat(3000))), None);
    }

    const LIVE: (i32, i32) = (420, 480);

    #[test]
    fn live_views_stay_off_the_card_and_cascade_on_screen() {
        for main in Anchor::ALL {
            let zone = card_zone(FHD, 1.0, main);
            let first = default_origin(FHD, 1.0, main, PaneKind::Live, 0, LIVE);
            let second = default_origin(FHD, 1.0, main, PaneKind::Live, 1, LIVE);
            assert!(!overlaps((first.0, first.1, LIVE.0, LIVE.1), zone), "live view over the card at {main:?}");
            assert_ne!(first, second, "{main:?}: two views on top of each other");
            for (x, y) in [first, second, default_origin(FHD, 1.0, main, PaneKind::Live, 2, LIVE)] {
                assert!(x >= 0 && x + LIVE.0 <= FHD.w as i32 && y >= 0 && y + LIVE.1 <= FHD.h as i32);
            }
        }
    }

    #[test]
    fn the_text_box_goes_where_the_cards_appear() {
        let size = (560, 68);
        for main in Anchor::ALL {
            let zone = card_zone(FHD, 1.0, main);
            let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Type, 0, size);
            assert!(overlaps((x, y, size.0, size.1), zone), "text box away from the cards at {main:?}");
            assert!(x >= 0 && x + size.0 <= FHD.w as i32 && y >= 0 && y + size.1 <= FHD.h as i32);
        }
    }
}

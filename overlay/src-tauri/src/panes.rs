//! Where pane windows go (ADR-015 §3). Pure, so it can be tested for layouts this machine doesn't have.
//!
//! A pane is another request's chip or the reader. With no remembered place, it goes in free
//! space away from the main window: request chips on the far side from the main window's
//! column, the reader on the other side, so neither covers the card in front. Dragged
//! somewhere, a kind remembers where, as a fraction of the work area, so it holds across
//! monitors and resolutions. A second pane of the same kind stacks beside the first.
//!
//! ADR-015 §9, §10: the waiting stack sits in a bottom corner, on the request chips' side (chips
//! that would come up from the bottom start above it), and grows upwards when it expands. The
//! text box goes where the cards appear, at the main window's anchored edge.

use crate::placement::{card_zone, Anchor, Area, MARGIN};

/// Space between stacked panes, CSS px.
pub const GAP: f64 = 8.0;
/// Room kept at the bottom of the chips' side for the compressed stack, CSS px.
pub const STACK_RESERVE: f64 = 84.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PaneKind {
    Request,
    Reader,
    /// The waiting stack (ADR-015 §9).
    Stack,
    /// The text box (ADR-015 §10): the one pane that takes the keyboard.
    Type,
    /// The tray menu (ADR-017): opened by a click on the tray icon, next to it.
    Tray,
}

impl PaneKind {
    pub fn from_id(id: &str) -> Option<PaneKind> {
        match id {
            "request" => Some(PaneKind::Request),
            "reader" => Some(PaneKind::Reader),
            "stack" => Some(PaneKind::Stack),
            "type" => Some(PaneKind::Type),
            "tray" => Some(PaneKind::Tray),
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
        (PaneKind::Request | PaneKind::Stack | PaneKind::Type, 1) => -1,
        (PaneKind::Request | PaneKind::Stack | PaneKind::Type, _) => 1,
        (PaneKind::Reader, -1) => 1,
        (PaneKind::Reader, _) => -1,
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

/// Request chips stack from the top unless the reader shares their side (then from the bottom).
fn chips_from_top(main: Anchor) -> bool {
    side(PaneKind::Request, main) != side(PaneKind::Reader, main)
}

/// Keep a rect inside the work area.
pub fn clamp(area: Area, (x, y): (i32, i32), (w, h): (i32, i32)) -> (i32, i32) {
    let max_x = area.x + (area.w as i32 - w).max(0);
    let max_y = area.y + (area.h as i32 - h).max(0);
    (x.clamp(area.x, max_x), y.clamp(area.y, max_y))
}

/// Where a pane of `size` (physical px) goes the first time: free space away from the main window.
/// `index` stacks the second and third of a kind beside the first.
pub fn default_origin(area: Area, scale: f64, main: Anchor, kind: PaneKind, index: u32, size: (i32, i32)) -> (i32, i32) {
    let scale = if scale.is_finite() && scale > 0.0 { scale } else { 1.0 };
    let m = (MARGIN * scale).round() as i32;
    let step = size.1 + (GAP * scale).round() as i32;
    if kind == PaneKind::Type {
        // Where the cards appear: the answer shows up right where the request was typed.
        let (zx, zy, zw, zh) = card_zone(area, scale, main);
        let x = zx + (zw - size.0) / 2;
        let y = if main.is_top() { zy } else { zy + zh - size.1 };
        return clamp(area, (x, y), size);
    }
    let x = if side(kind, main) < 0 { area.x + m } else { area.x + area.w as i32 - size.0 - m };
    let reserve = (STACK_RESERVE * scale).round() as i32;
    let y = match kind {
        PaneKind::Reader => area.y + m,
        PaneKind::Stack => area.y + area.h as i32 - m - size.1,
        PaneKind::Request if chips_from_top(main) => area.y + m + step * index as i32,
        PaneKind::Request | PaneKind::Type => area.y + area.h as i32 - m - reserve - size.1 - step * index as i32,
        PaneKind::Tray => area.y + area.h as i32 - m - size.1,
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

/// The reader's height at most: 70 % of the work area.
pub fn max_height(area: Area) -> i32 {
    (area.h as f64 * 0.7).round() as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::placement::card_zone;

    const FHD: Area = Area { x: 0, y: 0, w: 1920, h: 1040 };
    const CHIP: (i32, i32) = (300, 44);
    const READER: (i32, i32) = (560, 600);

    fn overlaps(a: (i32, i32, i32, i32), b: (i32, i32, i32, i32)) -> bool {
        a.0 < b.0 + b.2 && b.0 < a.0 + a.2 && a.1 < b.1 + b.3 && b.1 < a.1 + a.3
    }

    #[test]
    fn panes_never_cover_the_card_in_front() {
        for main in Anchor::ALL {
            let zone = card_zone(FHD, 1.0, main);
            for index in 0..3 {
                let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Request, index, CHIP);
                assert!(!overlaps((x, y, CHIP.0, CHIP.1), zone), "chip {index} over the card at {main:?}");
            }
            let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Reader, 0, READER);
            assert!(!overlaps((x, y, READER.0, READER.1), zone), "reader over the card at {main:?}");
        }
    }

    #[test]
    fn chips_and_reader_do_not_overlap() {
        for main in Anchor::ALL {
            let (rx, ry) = default_origin(FHD, 1.0, main, PaneKind::Reader, 0, READER);
            for index in 0..3 {
                let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Request, index, CHIP);
                assert!(!overlaps((x, y, CHIP.0, CHIP.1), (rx, ry, READER.0, READER.1)), "{main:?} chip {index}");
            }
        }
    }

    #[test]
    fn chips_stack_without_overlapping() {
        let a = default_origin(FHD, 1.0, Anchor::BottomCenter, PaneKind::Request, 0, CHIP);
        let b = default_origin(FHD, 1.0, Anchor::BottomCenter, PaneKind::Request, 1, CHIP);
        assert_eq!(a.0, b.0);
        assert!((b.1 - a.1).abs() >= CHIP.1);
    }

    #[test]
    fn remembered_places_round_trip_and_stay_on_screen() {
        let f = to_fraction(FHD, (1200, 300));
        assert_eq!(remembered_origin(FHD, 1.0, f, 0, CHIP), (1200, 300));
        assert_eq!(remembered_origin(FHD, 1.0, f, 1, CHIP), (1200, 352));
        // Remembered on a big monitor, shown on a small one: still inside.
        let small = Area { x: -1280, y: 0, w: 1280, h: 720 };
        let (x, y) = remembered_origin(small, 1.0, (0.99, 0.99), 0, READER);
        assert!(x >= small.x && x + READER.0 <= small.x + small.w as i32);
        assert!(y >= small.y && y + READER.1 <= small.y + small.h as i32);
    }

    #[test]
    fn kinds_parse() {
        assert_eq!(PaneKind::from_id("request"), Some(PaneKind::Request));
        assert_eq!(PaneKind::from_id("reader"), Some(PaneKind::Reader));
        assert_eq!(PaneKind::from_id("stack"), Some(PaneKind::Stack));
        assert_eq!(PaneKind::from_id("type"), Some(PaneKind::Type));
        assert_eq!(PaneKind::from_id("tray"), Some(PaneKind::Tray));
        assert_eq!(PaneKind::from_id("main"), None);
        assert!(PaneKind::Stack.grows_up() && !PaneKind::Request.grows_up());
    }

    const STACK: (i32, i32) = (300, 72);

    #[test]
    fn the_stack_sits_in_a_bottom_corner_clear_of_the_card_the_chips_and_the_reader() {
        for main in Anchor::ALL {
            let (x, y) = default_origin(FHD, 1.0, main, PaneKind::Stack, 0, STACK);
            let stack = (x, y, STACK.0, STACK.1);
            assert_eq!(y + STACK.1, FHD.h as i32 - MARGIN as i32, "{main:?}: not at the bottom");
            assert!(x == MARGIN as i32 || x + STACK.0 == FHD.w as i32 - MARGIN as i32, "{main:?}: not in a corner");
            assert!(!overlaps(stack, card_zone(FHD, 1.0, main)), "stack over the card at {main:?}");
            let (rx, ry) = default_origin(FHD, 1.0, main, PaneKind::Reader, 0, READER);
            assert!(!overlaps(stack, (rx, ry, READER.0, READER.1)), "stack under the reader at {main:?}");
            for index in 0..5 {
                let (cx, cy) = default_origin(FHD, 1.0, main, PaneKind::Request, index, CHIP);
                assert!(!overlaps(stack, (cx, cy, CHIP.0, CHIP.1)), "stack under chip {index} at {main:?}");
            }
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

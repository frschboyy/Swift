//! Where the overlay goes on a monitor (PLAN.md §5, ADR-009). Pure, so it can be
//! tested for layouts this machine doesn't have.
//!
//! The window is a fixed, mostly transparent box; the cards draw at one of its
//! edges. It sits at one of six anchors on the cursor's monitor: the owner picks
//! one from the tray menu or by dragging a card (it snaps to the nearest), and
//! smart placement flips it to the opposite edge when its cards would cover the
//! text caret, i.e. what the owner is typing.

use serde::{Deserialize, Serialize};

/// Overlay size in CSS px.
pub const OVERLAY_W: f64 = 720.0;
pub const OVERLAY_H: f64 = 560.0;
/// Gap to the work area's edges, CSS px.
pub const MARGIN: f64 = 12.0;
/// Where cards actually paint inside the window, measured from the anchored edge (CSS px):
/// the card's max width plus the stage padding, and the tallest usual card.
pub const CARD_ZONE_W: f64 = 512.0;
pub const CARD_ZONE_H: f64 = 340.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Anchor {
    TopLeft,
    TopCenter,
    TopRight,
    BottomLeft,
    BottomCenter,
    BottomRight,
}

impl Default for Anchor {
    fn default() -> Self {
        Anchor::BottomCenter
    }
}

impl Anchor {
    pub const ALL: [Anchor; 6] = [
        Anchor::TopLeft,
        Anchor::TopCenter,
        Anchor::TopRight,
        Anchor::BottomLeft,
        Anchor::BottomCenter,
        Anchor::BottomRight,
    ];

    pub fn is_top(self) -> bool {
        matches!(self, Anchor::TopLeft | Anchor::TopCenter | Anchor::TopRight)
    }

    /// -1 left, 0 centre, 1 right.
    pub fn column(self) -> i32 {
        match self {
            Anchor::TopLeft | Anchor::BottomLeft => -1,
            Anchor::TopCenter | Anchor::BottomCenter => 0,
            Anchor::TopRight | Anchor::BottomRight => 1,
        }
    }

    fn from_parts(top: bool, column: i32) -> Anchor {
        match (top, column) {
            (true, -1) => Anchor::TopLeft,
            (true, 0) => Anchor::TopCenter,
            (true, _) => Anchor::TopRight,
            (false, -1) => Anchor::BottomLeft,
            (false, 0) => Anchor::BottomCenter,
            (false, _) => Anchor::BottomRight,
        }
    }

    /// The same column on the other edge.
    pub fn flipped(self) -> Anchor {
        Anchor::from_parts(!self.is_top(), self.column())
    }

    /// Stable id, used in overlay.json, tray menu ids and the frontend's layout.
    pub fn id(self) -> &'static str {
        match self {
            Anchor::TopLeft => "top-left",
            Anchor::TopCenter => "top-center",
            Anchor::TopRight => "top-right",
            Anchor::BottomLeft => "bottom-left",
            Anchor::BottomCenter => "bottom-center",
            Anchor::BottomRight => "bottom-right",
        }
    }

    pub fn from_id(id: &str) -> Option<Anchor> {
        Anchor::ALL.into_iter().find(|a| a.id() == id)
    }

    pub fn label(self) -> &'static str {
        match self {
            Anchor::TopLeft => "Top left",
            Anchor::TopCenter => "Top centre",
            Anchor::TopRight => "Top right",
            Anchor::BottomLeft => "Bottom left",
            Anchor::BottomCenter => "Bottom centre",
            Anchor::BottomRight => "Bottom right",
        }
    }
}

/// A monitor's work area (excludes the taskbar), in physical pixels of the virtual desktop.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Area {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
}

/// A rect in physical pixels: x, y, w, h.
pub type Rect = (i32, i32, i32, i32);

fn sane(scale: f64) -> f64 {
    if scale.is_finite() && scale > 0.0 {
        scale
    } else {
        1.0
    }
}

fn contains((x, y, w, h): Rect, (px, py): (i32, i32)) -> bool {
    px >= x && px < x + w && py >= y && py < y + h
}

/// The overlay's rect in physical pixels: at `anchor` in `area`, scaled by the
/// monitor's DPI factor, never larger than the work area and never outside it.
pub fn overlay_rect(area: Area, scale: f64, anchor: Anchor) -> Rect {
    let scale = sane(scale);
    let (aw, ah) = (area.w as i32, area.h as i32);
    let w = ((OVERLAY_W * scale).round() as i32).min(aw);
    let h = ((OVERLAY_H * scale).round() as i32).min(ah);
    let mx = ((MARGIN * scale).round() as i32).min(aw - w);
    let my = ((MARGIN * scale).round() as i32).min(ah - h);
    let x = match anchor.column() {
        -1 => area.x + mx,
        0 => area.x + (aw - w) / 2,
        _ => area.x + aw - w - mx,
    };
    let y = if anchor.is_top() { area.y + my } else { area.y + ah - h - my };
    (x, y, w, h)
}

/// The overlay's rect where the owner dropped it (`dropped`: its top-left corner as a fraction
/// of the work area), the same size as at an anchor and kept inside the work area.
pub fn dropped_rect(area: Area, scale: f64, anchor: Anchor, (fx, fy): (f64, f64)) -> Rect {
    let (_, _, w, h) = overlay_rect(area, scale, anchor);
    let x = area.x + (fx.clamp(0.0, 1.0) * area.w as f64).round() as i32;
    let y = area.y + (fy.clamp(0.0, 1.0) * area.h as f64).round() as i32;
    let x = x.clamp(area.x, area.x + (area.w as i32 - w).max(0));
    let y = y.clamp(area.y, area.y + (area.h as i32 - h).max(0));
    (x, y, w, h)
}

/// Where a window's top-left corner is, as a fraction of the work area (what `dropped` keeps).
pub fn to_fraction(area: Area, (x, y): (i32, i32)) -> (f64, f64) {
    (
        ((x - area.x) as f64 / area.w.max(1) as f64).clamp(0.0, 1.0),
        ((y - area.y) as f64 / area.h.max(1) as f64).clamp(0.0, 1.0),
    )
}

/// The part of the overlay where cards paint, in physical pixels: a band at the anchored edge.
pub fn card_zone(area: Area, scale: f64, anchor: Anchor) -> Rect {
    card_zone_in(overlay_rect(area, scale, anchor), scale, anchor)
}

/// The same for an overlay at `rect` (where the owner dropped it, say), drawing at `anchor`'s edge.
pub fn card_zone_in((x, y, w, h): Rect, scale: f64, anchor: Anchor) -> Rect {
    let scale = sane(scale);
    let zw = ((CARD_ZONE_W * scale).round() as i32).min(w);
    let zh = ((CARD_ZONE_H * scale).round() as i32).min(h);
    let zx = match anchor.column() {
        -1 => x,
        0 => x + (w - zw) / 2,
        _ => x + w - zw,
    };
    let zy = if anchor.is_top() { y } else { y + h - zh };
    (zx, zy, zw, zh)
}

/// Smart placement: `preferred`, unless its cards would cover one of `avoid` (the text
/// caret) and the opposite edge wouldn't. Never moves sideways: the owner chose the column.
pub fn choose_anchor(area: Area, scale: f64, preferred: Anchor, avoid: &[(i32, i32)]) -> Anchor {
    let covers = |a: Anchor| avoid.iter().any(|p| contains(card_zone(area, scale, a), *p));
    if covers(preferred) && !covers(preferred.flipped()) {
        preferred.flipped()
    } else {
        preferred
    }
}

fn overlaps((ax, ay, aw, ah): Rect, (bx, by, bw, bh): Rect) -> bool {
    ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah && aw > 0 && ah > 0 && bw > 0 && bh > 0
}

fn centre((x, y, w, h): Rect) -> (f64, f64) {
    (x as f64 + w as f64 / 2.0, y as f64 + h as f64 / 2.0)
}

/// A10 (owner checks 203, 254): a window in a higher z-order band than Swift's (Task Manager with
/// "Always on top" is in band 16; every ordinary app, Swift included, is in band 1) stays in front
/// of Swift whatever Swift does. When one of `covers` lies over where the cards paint at the
/// owner's spot (`home_zone`: their anchor's, or where they dropped it), this is the anchor nearest to it whose card zone none
/// covers. `None` means stay home: nothing covers it, or every anchor is covered (nowhere better).
pub fn uncovered_anchor(area: Area, scale: f64, home_zone: Rect, covers: &[Rect]) -> Option<Anchor> {
    let covered = |zone: Rect| covers.iter().any(|c| overlaps(zone, *c));
    if !covered(home_zone) {
        return None;
    }
    let (hx, hy) = centre(home_zone);
    Anchor::ALL
        .into_iter()
        .map(|a| (a, card_zone(area, scale, a)))
        .filter(|(_, zone)| !covered(*zone))
        .map(|(a, zone)| {
            let (x, y) = centre(zone);
            (a, (x - hx).powi(2) + (y - hy).powi(2))
        })
        .min_by(|l, r| l.1.total_cmp(&r.1)) // first in `ALL` on a tie
        .map(|(a, _)| a)
}

/// Where the overlay goes given the windows Swift can't come in front of (A10): its home (the
/// owner's anchor `home` at `home_rect`, which is where they dropped it if they did) unless one of
/// `covers` lies over the cards there; then the nearest uncovered anchor. Always judged from home,
/// so once nothing covers it Swift is back where the owner put it. The bool: moved off home.
pub fn settle(area: Area, scale: f64, home: Anchor, home_rect: Rect, covers: &[Rect]) -> (Anchor, Rect, bool) {
    match uncovered_anchor(area, scale, card_zone_in(home_rect, scale, home), covers) {
        Some(anchor) => (anchor, overlay_rect(area, scale, anchor), true),
        None => (home, home_rect, false),
    }
}

/// Where a dragged card snaps: the anchor for the part of the work area it was dropped in
/// (thirds across, halves down).
pub fn nearest_anchor(area: Area, point: (i32, i32)) -> Anchor {
    let rx = (point.0 - area.x) as f64 / area.w.max(1) as f64;
    let ry = (point.1 - area.y) as f64 / area.h.max(1) as f64;
    let column = if rx < 1.0 / 3.0 {
        -1
    } else if rx < 2.0 / 3.0 {
        0
    } else {
        1
    };
    Anchor::from_parts(ry < 0.5, column)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FHD: Area = Area { x: 0, y: 0, w: 1920, h: 1040 }; // 1080p minus a 40 px taskbar
    const BC: Anchor = Anchor::BottomCenter;

    #[test]
    fn primary_monitor_at_100_percent() {
        assert_eq!(overlay_rect(FHD, 1.0, BC), (600, 468, 720, 560));
    }

    #[test]
    fn scales_with_dpi_and_stays_bottom_centred() {
        // 150%: the development laptop (1920x1080 work area at 1.5x).
        let laptop = Area { x: 0, y: 0, w: 1920, h: 1080 };
        assert_eq!(overlay_rect(laptop, 1.5, BC), (420, 222, 1080, 840));
        // 200% on a 4K monitor.
        let uhd = Area { x: 0, y: 0, w: 3840, h: 2100 };
        let (x, y, w, h) = overlay_rect(uhd, 2.0, BC);
        assert_eq!((w, h), (1440, 1120));
        assert_eq!(x + w / 2, 3840 / 2);
        assert_eq!(y + h + 24, 2100);
    }

    #[test]
    fn secondary_monitors_left_above_and_right_of_primary() {
        // A monitor to the left of the primary has negative x; one above has negative y.
        let left = Area { x: -2560, y: -200, w: 2560, h: 1400 };
        for anchor in Anchor::ALL {
            let (x, y, w, h) = overlay_rect(left, 1.25, anchor);
            assert!(x >= left.x && x + w <= left.x + left.w as i32, "{anchor:?}");
            assert!(y >= left.y && y + h <= left.y + left.h as i32, "{anchor:?}");
        }
        assert_eq!(overlay_rect(Area { x: 1920, ..FHD }, 1.0, BC), (2520, 468, 720, 560));
    }

    #[test]
    fn never_larger_than_a_small_work_area() {
        let small = Area { x: 100, y: 50, w: 800, h: 600 };
        for anchor in Anchor::ALL {
            let (x, y, w, h) = overlay_rect(small, 1.5, anchor);
            assert_eq!((w, h), (800, 600));
            assert_eq!((x, y), (100, 50));
        }
    }

    #[test]
    fn bad_scale_falls_back_to_one() {
        assert_eq!(overlay_rect(FHD, 0.0, BC), overlay_rect(FHD, 1.0, BC));
        assert_eq!(overlay_rect(FHD, f64::NAN, BC), overlay_rect(FHD, 1.0, BC));
    }

    #[test]
    fn corners_keep_a_margin() {
        assert_eq!(overlay_rect(FHD, 1.0, Anchor::TopLeft), (12, 12, 720, 560));
        assert_eq!(overlay_rect(FHD, 1.0, Anchor::TopRight), (1920 - 720 - 12, 12, 720, 560));
        assert_eq!(overlay_rect(FHD, 1.0, Anchor::BottomRight), (1920 - 720 - 12, 468, 720, 560));
    }

    #[test]
    fn card_zone_sits_at_the_anchored_edge() {
        // Bottom centre: a 512 x 340 band at the bottom middle of the window.
        assert_eq!(card_zone(FHD, 1.0, BC), (600 + 104, 468 + 220, 512, 340));
        assert_eq!(card_zone(FHD, 1.0, Anchor::TopLeft), (12, 12, 512, 340));
        assert_eq!(card_zone(FHD, 1.0, Anchor::TopRight), (1920 - 12 - 512, 12, 512, 340));
    }

    #[test]
    fn smart_placement_flips_away_from_the_caret() {
        let caret_low = (960, 1000); // typing near the bottom of the screen
        assert_eq!(choose_anchor(FHD, 1.0, BC, &[caret_low]), Anchor::TopCenter);
        // Caret elsewhere, or no caret: stay where the owner put it.
        assert_eq!(choose_anchor(FHD, 1.0, BC, &[(960, 300)]), BC);
        assert_eq!(choose_anchor(FHD, 1.0, BC, &[]), BC);
        // Caret beside the card zone (bottom left) doesn't flip a bottom-centre overlay.
        assert_eq!(choose_anchor(FHD, 1.0, BC, &[(100, 1000)]), BC);
        // Top right -> bottom right when typing in the top right corner.
        assert_eq!(choose_anchor(FHD, 1.0, Anchor::TopRight, &[(1800, 40)]), Anchor::BottomRight);
    }

    #[test]
    fn smart_placement_stays_when_both_edges_are_covered() {
        // A tiny work area where the zones overlap: nowhere better to go.
        let tiny = Area { x: 0, y: 0, w: 600, h: 400 };
        assert_eq!(choose_anchor(tiny, 1.0, BC, &[(300, 200)]), BC);
    }

    #[test]
    fn a_dropped_overlay_stays_where_it_was_dropped() {
        let (x, y, w, h) = overlay_rect(FHD, 1.0, Anchor::TopCenter);
        let dropped = to_fraction(FHD, (x + 300, y + 200));
        let r = dropped_rect(FHD, 1.0, Anchor::TopCenter, dropped);
        assert_eq!(r, (x + 300, y + 200, w, h));
        // Never off the work area, whatever was remembered.
        let (rx, ry, _, _) = dropped_rect(FHD, 1.0, Anchor::TopCenter, (1.0, 1.0));
        assert!(rx + w <= FHD.x + FHD.w as i32 && ry + h <= FHD.y + FHD.h as i32);
    }

    #[test]
    fn drops_snap_to_the_nearest_anchor() {
        assert_eq!(nearest_anchor(FHD, (100, 100)), Anchor::TopLeft);
        assert_eq!(nearest_anchor(FHD, (960, 100)), Anchor::TopCenter);
        assert_eq!(nearest_anchor(FHD, (1900, 1000)), Anchor::BottomRight);
        assert_eq!(nearest_anchor(FHD, (700, 900)), Anchor::BottomCenter);
        // Secondary monitor with a negative origin.
        let left = Area { x: -2560, y: -200, w: 2560, h: 1400 };
        assert_eq!(nearest_anchor(left, (-2500, -150)), Anchor::TopLeft);
    }

    /// Task Manager's default size, about 830 x 620 at 100%, wherever the owner left it.
    fn task_manager_at(x: i32, y: i32) -> Rect {
        (x, y, 830, 620)
    }

    #[test]
    fn a_window_swift_cannot_come_in_front_of_moves_the_cards_to_the_nearest_uncovered_anchor() {
        // Check 254: Task Manager over the orb at bottom centre.
        let over_orb = task_manager_at(560, 400);
        let home = card_zone(FHD, 1.0, BC);
        let moved = uncovered_anchor(FHD, 1.0, home, &[over_orb]).expect("the cards must move");
        assert!(!overlaps(card_zone(FHD, 1.0, moved), over_orb), "{moved:?} is still covered");
        assert_eq!(moved, Anchor::TopCenter, "the nearest uncovered anchor to bottom centre");
        // Task Manager in the bottom-right corner, over a bottom-right Swift: top right is nearer
        // than bottom left, and free.
        let corner = task_manager_at(1920 - 830, 1040 - 620);
        let home = card_zone(FHD, 1.0, Anchor::BottomRight);
        assert_eq!(uncovered_anchor(FHD, 1.0, home, &[corner]), Some(Anchor::TopRight));
    }

    #[test]
    fn the_owners_anchor_is_kept_when_nothing_covers_it() {
        let home = card_zone(FHD, 1.0, BC);
        assert_eq!(uncovered_anchor(FHD, 1.0, home, &[]), None);
        // Task Manager elsewhere on the screen: Swift stays (and returns) home.
        assert_eq!(uncovered_anchor(FHD, 1.0, home, &[task_manager_at(0, 0)]), None);
        // Touching the card zone's edge isn't covering it.
        let (zx, zy, _, _) = home;
        assert_eq!(uncovered_anchor(FHD, 1.0, home, &[(zx - 100, zy - 100, 100, 100)]), None);
    }

    #[test]
    fn nowhere_uncovered_stays_home() {
        // A maximised Task Manager covers every anchor: moving wouldn't help.
        let home = card_zone(FHD, 1.0, BC);
        assert_eq!(uncovered_anchor(FHD, 1.0, home, &[(0, 0, 1920, 1040)]), None);
    }

    #[test]
    fn a_dropped_overlay_is_judged_where_it_was_dropped() {
        // The owner dropped it in the middle; a window over it reaches up into top centre's zone
        // too, so the nearest uncovered anchor is bottom centre's.
        let dropped = (700, 300, 512, 340);
        let over = (650, 250, 300, 200);
        assert_eq!(uncovered_anchor(FHD, 1.0, dropped, &[over]), Some(Anchor::BottomCenter));
        // Not covered where it was dropped, though bottom centre's zone would be: it stays.
        let low = (700, 800, 300, 200);
        assert_eq!(uncovered_anchor(FHD, 1.0, dropped, &[low]), None);
    }

    #[test]
    fn swift_goes_back_to_the_owners_spot_once_nothing_covers_it() {
        // The owner dropped the overlay low in the middle; Task Manager then came over it.
        let home_rect = dropped_rect(FHD, 1.0, BC, (0.3, 0.45));
        let over = task_manager_at(500, 400);
        let (anchor, rect, moved) = settle(FHD, 1.0, BC, home_rect, &[over]);
        assert!(moved);
        assert_eq!(rect, overlay_rect(FHD, 1.0, anchor));
        assert!(!overlaps(card_zone(FHD, 1.0, anchor), over));
        // Task Manager closed, or moved away: back to exactly where the owner dropped it.
        assert_eq!(settle(FHD, 1.0, BC, home_rect, &[]), (BC, home_rect, false));
        assert_eq!(settle(FHD, 1.0, BC, home_rect, &[task_manager_at(1090, 0)]), (BC, home_rect, false));
    }

    #[test]
    fn anchor_ids_round_trip() {
        for anchor in Anchor::ALL {
            assert_eq!(Anchor::from_id(anchor.id()), Some(anchor));
            assert_eq!(anchor.flipped().flipped(), anchor);
            assert_ne!(anchor.flipped().is_top(), anchor.is_top());
        }
        assert_eq!(Anchor::from_id("middle"), None);
    }
}

//! Where the overlay goes on a monitor (PLAN.md §5). Pure, so it can be tested
//! for layouts this machine doesn't have.

/// Overlay size in CSS px. The window sits bottom-centre on the cursor's monitor.
pub const OVERLAY_W: f64 = 720.0;
pub const OVERLAY_H: f64 = 560.0;
pub const BOTTOM_MARGIN: f64 = 12.0;

/// A monitor's work area (excludes the taskbar), in physical pixels of the virtual desktop.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Area {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
}

/// The overlay's rect in physical pixels: bottom-centred in `area`, scaled by the
/// monitor's DPI factor, never larger than the work area and never outside it.
pub fn overlay_rect(area: Area, scale: f64) -> (i32, i32, i32, i32) {
    let scale = if scale.is_finite() && scale > 0.0 { scale } else { 1.0 };
    let w = ((OVERLAY_W * scale).round() as i32).min(area.w as i32);
    let h = ((OVERLAY_H * scale).round() as i32).min(area.h as i32);
    let margin = ((BOTTOM_MARGIN * scale).round() as i32).min(area.h as i32 - h);
    let x = area.x + (area.w as i32 - w) / 2;
    let y = area.y + area.h as i32 - h - margin;
    (x, y, w, h)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FHD: Area = Area { x: 0, y: 0, w: 1920, h: 1040 }; // 1080p minus a 40 px taskbar

    #[test]
    fn primary_monitor_at_100_percent() {
        assert_eq!(overlay_rect(FHD, 1.0), (600, 468, 720, 560));
    }

    #[test]
    fn scales_with_dpi_and_stays_bottom_centred() {
        // 150%: the development laptop (1920x1080 work area at 1.5x).
        let laptop = Area { x: 0, y: 0, w: 1920, h: 1080 };
        assert_eq!(overlay_rect(laptop, 1.5), (420, 222, 1080, 840));
        // 200% on a 4K monitor.
        let uhd = Area { x: 0, y: 0, w: 3840, h: 2100 };
        let (x, y, w, h) = overlay_rect(uhd, 2.0);
        assert_eq!((w, h), (1440, 1120));
        assert_eq!(x + w / 2, 3840 / 2);
        assert_eq!(y + h + 24, 2100);
    }

    #[test]
    fn secondary_monitors_left_above_and_right_of_primary() {
        // A monitor to the left of the primary has negative x; one above has negative y.
        let left = Area { x: -2560, y: -200, w: 2560, h: 1400 };
        let (x, y, w, h) = overlay_rect(left, 1.25);
        assert!(x >= left.x && x + w <= left.x + left.w as i32);
        assert!(y >= left.y && y + h <= left.y + left.h as i32);
        assert_eq!(overlay_rect(Area { x: 1920, ..FHD }, 1.0), (2520, 468, 720, 560));
    }

    #[test]
    fn never_larger_than_a_small_work_area() {
        let small = Area { x: 100, y: 50, w: 800, h: 600 };
        let (x, y, w, h) = overlay_rect(small, 1.5);
        assert_eq!((w, h), (800, 600));
        assert_eq!((x, y), (100, 50));
    }

    #[test]
    fn bad_scale_falls_back_to_one() {
        assert_eq!(overlay_rect(FHD, 0.0), overlay_rect(FHD, 1.0));
        assert_eq!(overlay_rect(FHD, f64::NAN), overlay_rect(FHD, 1.0));
    }
}

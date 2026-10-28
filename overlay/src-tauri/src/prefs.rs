//! The overlay's own preferences (ADR-009): where it sits and whether smart
//! placement may move it. Kept in `%LOCALAPPDATA%\Swift\overlay.json`, not
//! config.yaml: they change from the tray menu and by dragging, and config.yaml
//! is the owner's file, which Swift never writes.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::placement::Anchor;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Prefs {
    /// Where the owner put the overlay.
    pub anchor: Anchor,
    /// Where the owner dropped the overlay after a drag, as a fraction of the work area (its
    /// top-left corner): it stays there instead of snapping to `anchor`, which still says which
    /// way cards grow. A Position choice from the tray clears it.
    pub dropped: Option<(f64, f64)>,
    /// Flip to the opposite edge when the cards would cover the text caret.
    pub smart: bool,
    /// Where the owner dragged each kind of pane window (ADR-015 §3), as fractions of the work area.
    pub panes: PanePlaces,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct PanePlaces {
    pub request: Option<(f64, f64)>,
    pub reader: Option<(f64, f64)>,
    /// The waiting stack: where its bottom-left corner was dropped (it grows upwards).
    pub stack: Option<(f64, f64)>,
    pub typing: Option<(f64, f64)>,
    /// The live view of a request (ADR-017 §7).
    pub live: Option<(f64, f64)>,
}

impl Default for Prefs {
    fn default() -> Self {
        Prefs { anchor: Anchor::default(), dropped: None, smart: true, panes: PanePlaces::default() }
    }
}

fn path() -> Option<PathBuf> {
    std::env::var_os("LOCALAPPDATA").map(|dir| PathBuf::from(dir).join("Swift").join("overlay.json"))
}

/// The saved preferences; defaults when there are none or they can't be read.
pub fn load() -> Prefs {
    path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

pub fn save(prefs: &Prefs) {
    let Some(path) = path() else { return };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    match serde_json::to_string_pretty(prefs) {
        Ok(text) => {
            if let Err(e) = std::fs::write(&path, text) {
                eprintln!("[overlay] could not save {}: {e}", path.display());
            }
        }
        Err(e) => eprintln!("[overlay] could not encode preferences: {e}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_partial_and_unknown_files() {
        let p: Prefs = serde_json::from_str(r#"{"anchor": "top-right"}"#).unwrap();
        assert_eq!(p, Prefs { anchor: Anchor::TopRight, dropped: None, smart: true, panes: PanePlaces::default() });
        let p: Prefs = serde_json::from_str(r#"{"smart": false, "later": 1}"#).unwrap();
        assert_eq!(p, Prefs { anchor: Anchor::BottomCenter, dropped: None, smart: false, panes: PanePlaces::default() });
        let p: Prefs = serde_json::from_str(r#"{"panes": {"reader": [0.1, 0.2]}}"#).unwrap();
        assert_eq!(p.panes, PanePlaces { reader: Some((0.1, 0.2)), ..PanePlaces::default() });
        assert!(serde_json::from_str::<Prefs>(r#"{"anchor": "middle"}"#).is_err());
    }
}

// The presence capsule (ADR-017, the owner's Capsule design): the small pill at the anchor that
// is Swift's body. Every card grows out of it. Pure: no DOM; main.ts draws what this says.
//
// What it shows, most urgent first:
// - the owner talking (listening, transcribing, or a microphone that hears nothing for 4 s);
// - Swift heard its name or the hotkey ("Listening…", before anything is transcribed);
// - Swift talking ("Speaking", with Stop);
// - listening paused, by the owner (mic off, with Resume) or by a locked screen or sleep. This is
//   the privacy indicator: it stays as long as the pause, never fades;
// - a card open: the orb alone, since the card says the rest (ADR-018 §2.5);
// - a request working;
// - otherwise the idle dot.

import type { UiState } from "./protocol";

export type Presence =
  | "idle" | "orb" | "heard" | "listening" | "transcribing" | "cant-hear" | "working" | "speaking" | "paused-mic" | "paused-locked";

/** Listening this long with nothing above room noise: "I can't hear you". */
export const QUIET_MS = 4000;
export const QUIET_LEVEL = 0.05;

export type CapsuleInput = {
  state: UiState;
  // The "Listening…" pulse is up (heard.ts).
  heard: boolean;
  // Listening, and nothing above room noise for QUIET_MS.
  quiet: boolean;
  speaking: boolean;
  // Why listening is off (presence), or null: "mic" (paused from the tray), "locked", "asleep".
  paused: "mic" | "locked" | "asleep" | null;
  // A card is on screen.
  cardOpen: boolean;
};

export function presence(i: CapsuleInput): Presence {
  if (i.state === "listening") return i.quiet ? "cant-hear" : "listening";
  if (i.state === "transcribing") return "transcribing";
  if (i.heard) return "heard";
  if (i.speaking) return "speaking";
  if (i.paused === "mic") return "paused-mic";
  if (i.paused) return "paused-locked";
  if (i.cardOpen) return "orb";
  if (i.state === "working") return "working";
  return "idle";
}

/** Why listening is off, from the ``presence`` message (null: it's on, or wake listening isn't used). */
export function pausedBy(p: { listening: boolean; wake: boolean; reason: string; paused?: boolean } | null): CapsuleInput["paused"] {
  if (!p) return null;
  if (p.paused) return "mic";
  if (!p.wake || p.listening) return null;
  if (p.reason === "locked") return "locked";
  if (p.reason === "asleep") return "asleep";
  return null;
}

export type CapsuleView = {
  // Bold first word(s), then the rest in a quieter colour.
  label: string;
  sub: string;
  // The one control: Stop while speaking, Resume while paused by the owner.
  button: "stop" | "resume" | null;
  // Clickable (a hit region): only with a button. Otherwise it is click-through.
  clickable: boolean;
};

const QUIET_TEXT = "I can't hear you. Check your microphone.";

/** The words on the capsule. ``transcript``: the live words; ``elapsed``: "0:12" while working. */
export function view(p: Presence, transcript: string, elapsed: string, paused: CapsuleInput["paused"]): CapsuleView {
  const plain = (label: string, sub = ""): CapsuleView => ({ label, sub, button: null, clickable: false });
  switch (p) {
    case "idle":
    case "orb":
      return plain("");
    case "heard":
      return plain("Listening…");
    case "listening":
      return plain("", transcript || "Listening");
    case "transcribing":
      return plain("", transcript || "Transcribing");
    case "cant-hear":
      return plain("", QUIET_TEXT);
    case "working":
      return plain("Working on it", elapsed);
    case "speaking":
      return { label: "Speaking", sub: "", button: "stop", clickable: true };
    case "paused-mic":
      return { label: "Not listening", sub: "Mic off", button: "resume", clickable: true };
    case "paused-locked":
      return plain("Not listening", paused === "asleep" ? "PC was asleep" : "Screen locked");
  }
}

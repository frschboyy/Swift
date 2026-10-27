// The "Listening…" pulse: shown the moment the backend hears Swift's name or the hotkey
// (``heard``), before anything is transcribed, so the owner never wonders whether to say it
// again (owner checks, 2026-10-27). It fades by itself; while Swift is visibly listening or
// transcribing the orb and its pill already say so, and the pulse stays out of the way.

export type HeardSource = "wake" | "ptt" | "queued";

// Long enough to notice, short enough not to linger over the card that follows.
export const HEARD_MS = 1800;

export type Heard = { source: HeardSource; text: string; until: number };

export function heard(now: number, source: HeardSource, text: string): Heard {
  return { source, text: text || "Listening…", until: now + HEARD_MS };
}

/** Whether the pulse shows now: until it fades, and not over the orb's own "Listening". */
export function heardVisible(h: Heard | null, state: string, now: number): boolean {
  return h !== null && now < h.until && state !== "listening" && state !== "transcribing";
}

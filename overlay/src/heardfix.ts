// Correcting what Swift heard (docs/design/heard-corrections.md). Pure: no DOM.
//
// The card's head row shows a flag after the heard words when the backend kept that request's clip
// (the final transcript's ``clip``). The flag opens the text box in fix mode; Enter there saves a label
// (``recordings`` "fix"), never a request or an answer: typed words never approve.

import type { UiState } from "./protocol";

/** What the owner can say went wrong: the backend's recordings.FIX_KINDS, in this order. */
export const FIX_KINDS: readonly { id: string; label: string }[] = [
  { id: "wrong_word", label: "Wrong word" },
  { id: "missed_word", label: "Missed a word" },
  { id: "extra_word", label: "Extra words" },
  { id: "name", label: "A name" },
  { id: "accent", label: "Accent" },
  { id: "background", label: "Background" },
  { id: "cut_off", label: "Cut off" },
  { id: "other", label: "Other" },
];

/** The flag shows on heard words Swift kept a clip for, and never on a Needs your OK card. */
export const canFlag = (clip: string | null, stage: UiState): boolean => !!clip && stage !== "confirm";

/** What to save from the fix pane, or null when nothing changed (same words, no kind picked). */
export function fixToSave(heard: string, said: string, kind: string | null): { said: string; kind: string } | null {
  const text = said.trim();
  if (!text || (text === heard.trim() && !kind)) return null;
  return { said: text, kind: kind ?? "other" };
}

// Halo SPEC §3 row 6: a hint shows at most 3 times, and stops once the owner uses it.
export const HINT_TIMES = 3;
export const HINT_KEY = "swift.hint.heard-fix";

/** Whether the hint is due, from its stored value (a count, or "used"). */
export const hintDue = (stored: string | null): boolean => stored !== "used" && (Number(stored) || 0) < HINT_TIMES;

/** The stored value after the hint showed once more. */
export const hintShown = (stored: string | null): string => (stored === "used" ? "used" : String((Number(stored) || 0) + 1));

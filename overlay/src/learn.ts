// A10/A11 (Explore, off by default): what the owner does by hand, counted on this PC, so the hint and the chips
// offer a verb only after it has been done LEARN_AT times. Pure, with the storage passed in; a storage that fails
// learns nothing.
import type { Hints } from "./protocol";

export const LEARN_AT = 3;
const KEY = "swift.learned";
type Store = Pick<Storage, "getItem" | "setItem">;

export function counts(store: Pick<Storage, "getItem">): Record<string, number> {
  try { return JSON.parse(store.getItem(KEY) ?? "{}") as Record<string, number>; } catch { return {}; }
}

/** One more manual use of `action` (the Copy or Show button). */
export function bump(store: Store, action: string): void {
  try { store.setItem(KEY, JSON.stringify({ ...counts(store), [action]: (counts(store)[action] ?? 0) + 1 })); } catch { /* learns nothing */ }
}

export type Say = { text: string; ok: boolean; learned?: boolean };

/** A10: the phrases the card accepts, then the verbs learned from repeats ("Put it in Word" after 3 Copy clicks). */
export function sayLines(card: "confirm" | "done", hints: Hints, store: Pick<Storage, "getItem">): Say[] {
  const seen = counts(store);
  const learned = card === "done" ? hints.verbs.filter((v) => (seen[v.learn] ?? 0) >= LEARN_AT).map((v) => ({ text: v.say, ok: v.ok, learned: true })) : [];
  return [...hints.say[card], ...learned].filter((l, i, all) => all.findIndex((o) => o.text === l.text) === i);
}

/** A11: at most 2 learned verbs, as chips, and only those its own card can do (`can`: "show" only where the card has
 * something to show). Each says what it does and whether it ends in an OK card. */
export function nextChips(hints: Hints, store: Pick<Storage, "getItem">, can: (learn: string) => boolean = () => true): { learn: string; label: string; say: string; ok: boolean }[] {
  const seen = counts(store);
  return hints.verbs.filter((v) => (seen[v.learn] ?? 0) >= LEARN_AT && can(v.learn)).slice(0, 2).map(({ learn, label, say, ok }) => ({ learn, label, say, ok }));
}

// The waiting stack (ADR-015 §9, the owner's design of 2026-10-27). Pure: no DOM, no Tauri.
//
// Everything that waits for the owner, as one stack of cards in a bottom corner: cards in line
// behind the one on screen, cards they put off ("Later"), the card held while they were away,
// and conversations left unfinished (stopped, a card unanswered, Swift's question unanswered).
// Compressed it takes little space; a double click expands it; a click anywhere else, or
// opening a card, compresses it again. Each card can be opened, skipped (to the back) or ended.
// The backend owns the list (``stack``); this decides how it looks.
//
// The Capsule redesign (ADR-017): "3 things need you" and "Next: …" when closed; open, each row
// has a type icon (a shield for a card waiting for an OK, a question mark for Swift's question,
// a pause for anything unfinished), its whole title (never cut) and why it waits.

import type { StackEntry } from "./protocol";

/** A card that just joined the stack glows this long, so the owner notices it. */
export const FRESH_MS = 4000;

export type Stack = {
  items: StackEntry[];
  expanded: boolean;
  // Ids that just joined, and until when they glow.
  fresh: string[];
  freshUntil: number;
};

export const initialStack: Stack = { items: [], expanded: false, fresh: [], freshUntil: 0 };

/** The backend's ``stack`` message. An empty stack can't stay expanded. */
export function onStack(s: Stack, items: StackEntry[], now: number): Stack {
  const known = new Set(s.items.map((i) => i.id));
  const fresh = items.filter((i) => !known.has(i.id)).map((i) => i.id);
  return {
    items,
    expanded: s.expanded && items.length > 0,
    fresh: fresh.length ? fresh : now < s.freshUntil ? s.fresh.filter((id) => items.some((i) => i.id === id)) : [],
    freshUntil: fresh.length ? now + FRESH_MS : s.freshUntil,
  };
}

export const expand = (s: Stack): Stack => (s.items.length ? { ...s, expanded: true } : s);
export const collapse = (s: Stack): Stack => (s.expanded ? { ...s, expanded: false } : s);

/** Opening a card from the stack compresses it: the card comes forward on its own. */
export function afterAction(s: Stack, action: "open" | "skip" | "end"): Stack {
  return action === "open" ? collapse(s) : s;
}

const ago = (ms: number): string => {
  const min = Math.floor(Math.max(0, ms) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min ago`;
};

/** The line under a card's title: why it waits, and since when. */
export function reasonLine(item: StackEntry, now: number): string {
  const since = ago(now - item.since_ms);
  switch (item.reason) {
    case "waiting":
      return "Waiting for your OK · behind another card";
    case "later":
      return `Waiting for your OK · put off ${since}`;
    case "held":
      return "Waiting for your OK · held while you were away";
    case "expired":
      return `Waiting for your OK · held, no answer in time · ${since}`;
    case "stopped":
      return `Unfinished · stopped before it was done · ${since}`;
    case "unanswered":
      return `Unfinished · a card went unanswered · ${since}`;
    case "asked":
      return `Unanswered question · ${since}`;
    case "due":
      return `Came due · ${since}`;
    default:
      return since;
  }
}

/** Every row's first button: open it (a card comes back, a conversation goes on). */
export const openLabel = (item: StackEntry): string => (item.kind === "due" ? "Done" : "Open");

/** The type icon on a row: a card waiting for an OK, Swift's question, or something unfinished. */
export function itemIcon(item: StackEntry): "shield" | "question" | "pause" | "bell" {
  if (item.kind === "due") return "bell";
  if (item.kind !== "parked") return "shield";
  return item.reason === "asked" ? "question" : "pause";
}

/** What the stack pane draws. */
export type StackView = {
  kind: "stack";
  expanded: boolean;
  items: { id: string; kind: StackEntry["kind"]; title: string; line: string; open: string; fresh: boolean; icon: ReturnType<typeof itemIcon> }[];
};

/** The stack pane's view, or null when nothing waits (no window). */
export function stackView(s: Stack, now: number): StackView | null {
  if (!s.items.length) return null;
  const glow = now < s.freshUntil ? new Set(s.fresh) : new Set<string>();
  return {
    kind: "stack",
    expanded: s.expanded,
    items: s.items.map((i) => ({
      id: i.id, kind: i.kind, title: i.title, line: reasonLine(i, now), open: openLabel(i), fresh: glow.has(i.id), icon: itemIcon(i),
    })),
  };
}

/** The compressed stack's one line: "3 things need you". */
export const countLine = (n: number): string => (n === 1 ? "1 thing needs you" : `${n} things need you`);

/** Under it: the one that comes next. */
export const nextLine = (v: StackView): string => (v.items.length ? `Next: ${v.items[0].title}` : "");

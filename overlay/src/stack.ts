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

import type { StackAction, StackEntry, TimerRow } from "./protocol";

/** A card that just joined the stack glows this long, so the owner notices it. */
export const FRESH_MS = 4000;

export type Stack = {
  items: StackEntry[];
  expanded: boolean;
  // Ids that just joined, and until when they glow.
  fresh: string[];
  freshUntil: number;
};

/** What waits for the owner: not a finished request (History, a pin), not a timer still counting (B14). */
export const waits = (i: { kind: StackEntry["kind"] }): boolean => i.kind !== "past" && i.kind !== "timer" && i.kind !== "pinned";

/** Pins shown on the shelf; the rest are counted ("+2 pinned"). */
export const SHELF_PINS = 4;

/** B14: a timer still counting, as a RUNNING row of the stack list (its Cancel ends it: ``timer:<id>``). */
export const timerEntry = (t: TimerRow): StackEntry =>
  ({ id: `timer:${t.id}`, kind: "timer", title: t.title || "Timer", reason: "timer", since_ms: t.set_ms, thread_id: null, expires_ms: t.due_ms });

export const initialStack: Stack = { items: [], expanded: false, fresh: [], freshUntil: 0 };

/** The backend's ``stack`` message. An empty stack can't stay expanded. */
export function onStack(s: Stack, items: StackEntry[], now: number): Stack {
  const known = new Set(s.items.map((i) => i.id));
  const fresh = items.filter((i) => !known.has(i.id) && waits(i)).map((i) => i.id);  // an answer doesn't glow
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
export function afterAction(s: Stack, action: StackAction): Stack {
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
      return "Needs your OK · behind another card";
    case "later":
      return `Needs your OK · put off ${since}`;
    case "held":
      return "Needs your OK · held while you were away";
    case "expired":
      return `Needs your OK · held, no answer in time · ${since}`;
    case "stopped":
      return `Unfinished · stopped before it was done · ${since}`;
    case "unanswered":
      return `Unfinished · a card went unanswered · ${since}`;
    case "asked":
      return `Unanswered question · ${since}`;
    case "due":
      return `Came due · ${since}`;
    case "timer": {
      // Whole minutes: the list redraws every 15 s, not every second (the orb's pill counts the seconds).
      const min = Math.ceil(Math.max(0, (item.expires_ms ?? now) - now) / 60000);
      return min > 1 ? `Timer · ${min} min left` : "Timer · under a minute left";
    }
    case "done":
      return `Done · ${since}`;
    case "failed":
      return `Failed · ${since}`;
    default:
      return since;
  }
}

/** Every row's first button: open it (a card comes back, a conversation goes on). */
export const openLabel = (item: StackEntry): string => (item.kind === "due" ? "Done" : item.kind === "timer" ? "Cancel" : "Open");

/** A row's one other action besides Open (owner, 2026-11-24: Skip only reordered the list, so it left the stack,
 * and End is named for what it does). ``confirm``: a second click within 3 s does it, since it can't be undone.
 * null: Open already does it (Done on a reminder, Cancel on a timer) or there's nothing to end (an earlier answer). */
export function secondAction(item: { kind: StackEntry["kind"]; reason?: string }): { label: string; tip: string; confirm: boolean } | null {
  switch (item.kind) {
    case "due": case "timer": case "past": case "pinned": return null;
    case "failed": return { label: "Dismiss", tip: "Remove it from the stack", confirm: false };
    case "parked":
      return item.reason === "asked"
        ? { label: "Cancel", tip: "Cancel the request", confirm: true }
        : { label: "Cancel", tip: "Cancel: Swift forgets where it got to", confirm: true };
    default: return { label: "Cancel", tip: "Cancel: it won't be done", confirm: true };
  }
}

/** The type icon on a row: a card waiting for an OK, Swift's question, or something unfinished. */
export function itemIcon(item: StackEntry): "shield" | "question" | "pause" | "bell" | "check" | "alert" | "timer" | "pin" {
  if (item.kind === "pinned") return "pin";
  if (item.kind === "timer") return "timer";
  if (item.kind === "failed") return "alert";
  if (item.kind === "past") return item.reason === "failed" ? "alert" : item.reason === "stopped" ? "pause" : "check";
  if (item.kind === "due") return "bell";
  if (item.kind !== "parked") return "shield";
  return item.reason === "asked" ? "question" : "pause";
}

/** How much of its time in the stack is left, 0 to 1, or null when it doesn't run out (the ring). */
export function timeLeft(item: StackEntry, now: number): number | null {
  if (!item.expires_ms || item.expires_ms <= item.since_ms) return null;
  return Math.min(1, Math.max(0, (item.expires_ms - now) / (item.expires_ms - item.since_ms)));
}

/** "Kept 8 more min": the ring's words, for the pointer and screen readers. */
export function leftLine(item: StackEntry, now: number): string {
  const min = Math.ceil(Math.max(0, (item.expires_ms ?? now) - now) / 60000);
  return min >= 120 ? `Kept ${Math.round(min / 60)} more hours` : min > 1 ? `Kept ${min} more min` : "Goes in a minute";
}

/** What the stack pane draws. */
export type StackView = {
  kind: "stack";
  expanded: boolean;
  items: { id: string; kind: StackEntry["kind"]; title: string; line: string; open: string; fresh: boolean; icon: ReturnType<typeof itemIcon>; left?: number | null; leftText?: string; second?: ReturnType<typeof secondAction> }[];
  // The main window's middle on the screen (CSS px): a card arriving comes from that side.
  mainX?: number;
};

/** The stack pane's view, or null when nothing waits and nothing is pinned (no window): answers from earlier today alone don't make a
 * pile (A1); they show under the waiting ones once it's open. */
export function stackView(s: Stack, now: number): StackView | null {
  if (!s.items.some((i) => waits(i) || i.kind === "pinned" || i.kind === "past")) return null;  // a pin or History keeps the corner
  const glow = now < s.freshUntil ? new Set(s.fresh) : new Set<string>();
  return {
    kind: "stack",
    expanded: s.expanded,
    items: s.items.map((i) => ({
      id: i.id, kind: i.kind, title: i.title, line: i.kind === "pinned" ? i.reason : reasonLine(i, now), open: openLabel(i), fresh: glow.has(i.id), icon: itemIcon(i),
      left: timeLeft(i, now), leftText: timeLeft(i, now) === null ? "" : leftLine(i, now), second: secondAction(i),
    })),
  };
}

/** History (owner, 2026-11-24): what the sidebar lists, pins first, then finished requests, newest first. */
export type HistoryView = {
  kind: "history";
  pins: { id: string; title: string; line: string }[];
  past: { id: string; title: string; line: string; icon: ReturnType<typeof itemIcon>; day: string }[];
};

const OUTCOME: Record<string, string> = { done: "Done", failed: "Failed", stopped: "Stopped" };

/** A day's heading: "Today", "Yesterday", or the date. */
export function dayLabel(ms: number, now: number): string {
  const day = (t: number): number => new Date(new Date(t).toDateString()).getTime();
  const back = Math.round((day(now) - day(ms)) / 86_400_000);
  return back === 0 ? "Today" : back === 1 ? "Yesterday" : new Date(ms).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

const clock = (ms: number): string => new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

export function historyView(s: Stack, now: number): HistoryView {
  return {
    kind: "history",
    pins: s.items.filter((i) => i.kind === "pinned").map((i) => ({ id: i.id, title: i.title, line: i.reason })),
    past: s.items.filter((i) => i.kind === "past").map((i) => ({
      id: i.id, title: i.title, line: `${OUTCOME[i.reason] ?? "Done"} · ${clock(i.since_ms)}`, icon: itemIcon(i), day: dayLabel(i.since_ms, now),
    })),
  };
}

/** Whether the corner shows the History link: there's something in it. */
export const hasHistory = (v: StackView): boolean => v.items.some((i) => i.kind === "past" || i.kind === "pinned");

/** Amber means an OK is waiting, nothing else (ADR-018 §2.6): the badge, and the glow of what just joined. */
export const needsOk = (v: StackView): boolean => v.items.some((i) => i.icon === "shield");
/** What waits, without the answers from earlier today (A1): the pile's count and its next line. */
export const waitingOnly = (v: StackView): StackView => ({ ...v, items: v.items.filter(waits) });
export const freshNeedsOk = (v: StackView): boolean => v.items.some((i) => i.fresh && i.icon === "shield");

/** The compressed stack's one line: "3 things need you". */
export const countLine = (n: number): string => (n === 1 ? "1 thing needs you" : `${n} things need you`);

/** Under it: the one that comes next; an OK waiting always leads, in amber (board 9 §1). */
export function nextLine(all: StackView): string {
  const v = waitingOnly(all);
  const ok = v.items.find((i) => i.icon === "shield");
  if (ok) return `Needs your OK · ${ok.title}`;
  return v.items.length ? `Next: ${v.items[0].title}` : "";
}

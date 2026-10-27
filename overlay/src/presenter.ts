// What the overlay shows, and for how long (ADR-013 §3). Pure: no DOM, no timers.
//
// main.ts feeds it what happens (backend messages, hover, a clock tick) and draws what it says.
// Lifetimes are deadlines in this state, checked on each tick, never setTimeout callbacks: a
// card can only fade if it is still the card on screen, so a finished request's fade can never
// hide the next request's card (the 2026-10-26 bug). New requests are recognised from run and
// thread ids, not from "listening", so new ways of starting one need no change here.
//
// Several requests at once (ADR-013 phase B): the backend's ``runs`` message names the one in
// front (``focus``) and the others as rows. While there are rows, only the request in front can
// change the card; the others' news is in their rows. When the card in front is gone and a row
// still runs, ``promote`` names the one to bring forward (main.ts asks the backend).

import type { UiState } from "./protocol";

export type CardKind = "none" | "listening" | "transcribing" | "working" | "confirm" | "result" | "error" | "notice";

const ACTIVE: ReadonlySet<CardKind> = new Set(["listening", "transcribing", "working", "confirm"]);
/** Mouse back off a paused card: at least this long before it fades. */
export const RESUME_MS = 2500;
/** Earlier turns of a thread shown above its card. */
export const HISTORY = 2;
/** Background rows drawn under the card; past that, "+N more" (ADR-013 §3.3). */
export const MAX_ROWS = 3;

/** Another request, one line under the card in front. */
export type Row = {
  runId: string;
  threadId: string | null;
  title: string;
  // "queued" (waiting for a slot), "listening" … "confirm", or how it ended: "result", "error", "done".
  state: string;
  activity: string | null;
  app: string | null;
  startedMs: number;
  // How it ended, in one line (ended rows only).
  summary: string;
};

const RUNNING: ReadonlySet<string> = new Set(["queued", "listening", "transcribing", "working", "confirm"]);

export type Card = {
  kind: CardKind;
  // The request (run) and conversation (thread) it belongs to; null for Swift's own notices.
  runId: string | null;
  threadId: string | null;
  // When it fades (ms, the caller's clock); null: stays (active, sticky, or nothing to fade).
  fadeAt: number | null;
};

export type Turn = { threadId: string; text: string };

export type Presenter = {
  card: Card;
  runId: string | null;
  threadId: string | null;
  // The thread's earlier answers, one line each (newest last), shown above its card.
  history: Turn[];
  // The last answer shown, so it can join the history if the thread goes on.
  lastAnswer: Turn | null;
  // A confirm card waiting for an answer: it must stay on screen (invariant)...
  pendingConfirm: string | null;
  // ...unless the owner is away: then it's put aside, hidden, until they're back (ADR-014 §4).
  held: string | null;
  // When the waiting card was first put aside (it says "1 card waiting, since …" once back); null: never.
  heldSince: number | null;
  // When the waiting card's countdown runs out (0: no countdown, or stopped while it is put aside).
  confirmDeadline: number;
  // The backend takes a reply without the wake phrase until then (0: not).
  followupUntil: number;
  // Hover or drag holds the card: the time left when it started.
  pausedLeft: number | null;
  // Several requests (ADR-013 phase B): the one in front, the others, and cards waiting behind the shown one.
  focus: string | null;
  rows: Row[];
  waiting: number;
};

export const initial: Presenter = {
  card: { kind: "none", runId: null, threadId: null, fadeAt: null },
  runId: null,
  threadId: null,
  history: [],
  lastAnswer: null,
  pendingConfirm: null,
  held: null,
  heldSince: null,
  confirmDeadline: 0,
  followupUntil: 0,
  pausedLeft: null,
  focus: null,
  rows: [],
  waiting: 0,
};

export const isActive = (p: Presenter): boolean => ACTIVE.has(p.card.kind);

/** No confirm card waiting any more. */
const noConfirm = { pendingConfirm: null, held: null, heldSince: null, confirmDeadline: 0 } as const;

/** Another request's message while there are rows: it updates its row, never the card. */
const notInFront = (p: Presenter, runId: string | null | undefined): boolean =>
  p.rows.length > 0 && p.focus !== null && !!runId && runId !== p.focus;

/** The ``runs`` message: who is in front, the others' rows, how many cards wait. */
export function onRuns(p: Presenter, focus: string | null, rows: Row[], waiting: number): Presenter {
  const next = { ...p, focus, rows: rows.filter((r) => r.runId !== focus), waiting };
  if (focus !== null && p.card.runId !== null && p.card.runId !== focus && next.rows.length) {
    // Another request comes to the front: its card replaces this one (the backend draws it next).
    return { ...next, card: { ...initial.card }, ...noConfirm, pausedLeft: null };
  }
  return next;
}

/** The rows to draw (at most MAX_ROWS) and how many more there are. */
export function visibleRows(p: Presenter): { rows: Row[]; more: number } {
  return { rows: p.rows.slice(0, MAX_ROWS), more: Math.max(0, p.rows.length - MAX_ROWS) };
}

/** Nothing in front any more but a row still runs: the newest one should come forward. */
export function promotion(p: Presenter): string | null {
  if (p.card.kind !== "none") return null;
  const running = p.rows.filter((r) => RUNNING.has(r.state) && r.state !== "queued");
  return running.length ? running[running.length - 1].runId : null;
}

export type StateChange = {
  p: Presenter;
  // A new request started: forget the last one's steps and artifacts.
  newRun: boolean;
  // ...and it continues the thread on screen (keep the earlier turns above it).
  continued: boolean;
  // Nothing is shown any more (idle).
  hide: boolean;
  // Another request's state while there are rows: ignored here (its row says it).
  ignored?: boolean;
};

/** A ``state`` message from the backend. */
export function onState(p: Presenter, state: UiState, runId: string | null, threadId: string | null): StateChange {
  const wasActive = isActive(p);
  const kind = state as CardKind;
  if (notInFront(p, runId)) return { p, newRun: false, continued: false, hide: false, ignored: true };
  if (state === "idle") {
    return { p: { ...p, card: { ...initial.card }, ...noConfirm }, newRun: false, continued: false, hide: true };
  }
  if (!ACTIVE.has(kind)) {
    // "result" / "error" come with their own message (onAnswer), which sets the card.
    return { p, newRun: false, continued: false, hide: false };
  }
  // A new request: from rest into an active state, or a run id we haven't seen while active.
  const newRun = !wasActive || (runId !== null && p.runId !== null && runId !== p.runId && kind !== "listening");
  let history = p.history;
  let continued = false;
  if (newRun) {
    continued = threadId !== null && threadId === p.threadId;
    history = continued && p.lastAnswer ? [...p.history, p.lastAnswer].slice(-HISTORY) : [];
  }
  return {
    p: {
      ...p,
      card: { kind, runId: runId ?? (newRun ? null : p.card.runId), threadId: threadId ?? p.threadId, fadeAt: null },
      runId: runId ?? (newRun ? null : p.runId),
      threadId: threadId ?? (newRun ? null : p.threadId),
      history,
      lastAnswer: newRun ? null : p.lastAnswer,
      ...(kind === "confirm" ? {} : noConfirm),
      followupUntil: newRun ? 0 : p.followupUntil,
      pausedLeft: null,
    },
    newRun,
    continued,
    hide: false,
  };
}

/** A confirm card was asked for: it must stay until answered. Its countdown starts now; drawn
 * again (a new draft version, "show me"), it keeps the one it had. */
export function onConfirm(p: Presenter, requestId: string, runId: string | null, timeoutS = 0, now = 0): Presenter {
  const card = { ...p.card, kind: "confirm" as const, runId: runId ?? p.card.runId, fadeAt: null };
  if (p.pendingConfirm === requestId) return { ...p, card };
  return { ...p, card, ...noConfirm, pendingConfirm: requestId, confirmDeadline: deadline(timeoutS, now) };
}

const deadline = (timeoutS: number, now: number): number => (timeoutS > 0 ? now + timeoutS * 1000 : 0);

/** The owner left (held) or came back: the waiting card is put aside, its countdown stopped; or
 * shown again with the time the backend gives it (at least a minute) and when it was put aside.
 * Other cards are untouched. */
export function onConfirmHold(p: Presenter, requestId: string, held: boolean, timeoutS = 0, now = 0): Presenter {
  if (p.pendingConfirm !== requestId) return p;
  if (held) return { ...p, held: requestId, heldSince: p.heldSince ?? now, confirmDeadline: 0 };
  return { ...p, held: null, confirmDeadline: deadline(timeoutS, now) };
}

/** The waiting card is on screen (not put aside while the owner is away). */
export const confirmVisible = (p: Presenter): boolean => p.pendingConfirm !== null && p.held === null;

/** The line on a card that came back: when it was put aside (ms), or null. */
export const waitingSince = (p: Presenter): number | null => (confirmVisible(p) ? p.heldSince : null);

export type Answer = {
  kind: "result" | "error" | "notice";
  runId?: string | null;
  threadId?: string | null;
  // One line for the thread's history ("Not added: Meeting, Thu 15:00").
  summary?: string;
  // How long it stays; null: until dismissed (sticky).
  ms: number | null;
};

/** A result, an error, or one of Swift's own notices. ``shown`` false: a notice the screen is too busy for. */
export function onAnswer(p: Presenter, a: Answer, now: number): { p: Presenter; shown: boolean } {
  if (a.kind === "notice" && isActive(p)) return { p, shown: false };  // never over a request
  if (notInFront(p, a.runId)) return { p, shown: false };  // its row says how it ended
  if (a.runId && p.runId && a.runId !== p.runId && isActive(p) && a.runId !== p.focus) return { p, shown: false };  // a late, stale answer
  const fadeAt = a.ms === null ? null : now + Math.max(a.ms, p.followupUntil > now ? p.followupUntil - now + 500 : 0);
  const thread = a.threadId ?? (a.kind === "notice" ? null : p.threadId);
  return {
    p: {
      ...p,
      card: { kind: a.kind, runId: a.runId ?? (a.kind === "notice" ? null : p.runId), threadId: thread, fadeAt },
      threadId: a.kind === "notice" ? p.threadId : thread,
      lastAnswer: a.summary && thread ? { threadId: thread, text: a.summary } : p.lastAnswer,
      ...noConfirm,
      pausedLeft: p.pausedLeft !== null && fadeAt !== null ? fadeAt - now : null,
    },
    shown: true,
  };
}

/** The backend's follow-up window opened or closed. The answer stays at least as long as it is open. */
export function onFollowup(p: Presenter, open: boolean, seconds: number, now: number): Presenter {
  if (!open) return { ...p, followupUntil: 0 };
  const until = now + seconds * 1000;
  const fadeAt = p.card.fadeAt !== null ? Math.max(p.card.fadeAt, until + 500) : null;
  return { ...p, followupUntil: until, card: { ...p.card, fadeAt } };
}

/** Hover or drag holds an answer; letting go gives it RESUME_MS more (ADR-009). */
export function onHold(p: Presenter, holding: boolean, now: number): Presenter {
  if (p.card.fadeAt === null) return p;
  if (holding) return p.pausedLeft !== null ? p : { ...p, pausedLeft: Math.max(0, p.card.fadeAt - now) };
  if (p.pausedLeft === null) return p;
  return { ...p, pausedLeft: null, card: { ...p.card, fadeAt: now + RESUME_MS } };
}

/** The owner closed the card. Only an answer or notice can be closed: a request goes on. */
export function onDismiss(p: Presenter): { p: Presenter; hide: boolean } {
  if (isActive(p) || p.card.kind === "none") return { p, hide: false };
  return { p: { ...p, card: { ...initial.card } }, hide: true };
}

/** The clock. ``hide``: the answer's time is up. ``followupLeft``: seconds of the reply window left (0: closed). */
export function tick(p: Presenter, now: number): { p: Presenter; hide: boolean; followupLeft: number } {
  let next = p;
  if (next.followupUntil && now >= next.followupUntil) next = { ...next, followupUntil: 0 };
  const followupLeft = next.followupUntil ? Math.ceil((next.followupUntil - now) / 1000) : 0;
  const due = next.card.fadeAt !== null && next.pausedLeft === null && now >= next.card.fadeAt;
  if (due && !isActive(next)) return { p: { ...next, card: { ...initial.card } }, hide: true, followupLeft };
  return { p: next, hide: false, followupLeft };
}

/** Rules that must always hold (checked in debug builds, and by the tests). */
export function violations(p: Presenter): string[] {
  const out: string[] = [];
  if (isActive(p) && p.card.fadeAt !== null) out.push(`an active ${p.card.kind} card has a fade deadline`);
  if (p.pendingConfirm && p.card.kind !== "confirm") out.push(`confirm ${p.pendingConfirm} is waiting but not on screen`);
  if (p.held && p.held !== p.pendingConfirm) out.push(`card ${p.held} is put aside but isn't waiting`);
  if (p.held && p.confirmDeadline) out.push(`card ${p.held} is put aside but still counting down`);
  if (!p.pendingConfirm && (p.heldSince !== null || p.confirmDeadline)) out.push("a countdown with no card waiting");
  if (p.history.length > HISTORY) out.push("too many earlier turns");
  if (p.history.some((t) => t.threadId !== p.threadId)) out.push("an earlier turn from another thread");
  // Several requests: never two cards fighting (ADR-013 §3.2).
  if (p.rows.length && p.focus && isActive(p) && p.card.runId && p.card.runId !== p.focus) {
    out.push(`the card on screen (${p.card.runId}) isn't the request in front (${p.focus})`);
  }
  if (p.rows.some((r) => r.runId === p.focus)) out.push("the request in front also has a row");
  if (new Set(p.rows.map((r) => r.runId)).size !== p.rows.length) out.push("a request has two rows");
  if (p.waiting > 0 && !p.pendingConfirm) out.push(`${p.waiting} cards wait but none is on screen`);
  if (visibleRows(p).rows.length > MAX_ROWS) out.push("too many rows");
  return out;
}

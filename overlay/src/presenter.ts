// What the overlay shows, and for how long (ADR-013 §3). Pure: no DOM, no timers.
//
// main.ts feeds it what happens (backend messages, hover, a clock tick) and draws what it says.
// Lifetimes are deadlines in this state, checked on each tick, never setTimeout callbacks: a
// card can only fade if it is still the card on screen, so a finished request's fade can never
// hide the next request's card (the 2026-10-26 bug). New requests are recognised from run and
// thread ids, not from "listening", so new ways of starting one need no change here.

import type { UiState } from "./protocol";

export type CardKind = "none" | "listening" | "transcribing" | "working" | "confirm" | "result" | "error" | "notice";

const ACTIVE: ReadonlySet<CardKind> = new Set(["listening", "transcribing", "working", "confirm"]);
/** Mouse back off a paused card: at least this long before it fades. */
export const RESUME_MS = 2500;
/** Earlier turns of a thread shown above its card. */
export const HISTORY = 2;

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
  // The backend takes a reply without the wake phrase until then (0: not).
  followupUntil: number;
  // Hover or drag holds the card: the time left when it started.
  pausedLeft: number | null;
};

export const initial: Presenter = {
  card: { kind: "none", runId: null, threadId: null, fadeAt: null },
  runId: null,
  threadId: null,
  history: [],
  lastAnswer: null,
  pendingConfirm: null,
  held: null,
  followupUntil: 0,
  pausedLeft: null,
};

export const isActive = (p: Presenter): boolean => ACTIVE.has(p.card.kind);

export type StateChange = {
  p: Presenter;
  // A new request started: forget the last one's steps and artifacts.
  newRun: boolean;
  // ...and it continues the thread on screen (keep the earlier turns above it).
  continued: boolean;
  // Nothing is shown any more (idle).
  hide: boolean;
};

/** A ``state`` message from the backend. */
export function onState(p: Presenter, state: UiState, runId: string | null, threadId: string | null): StateChange {
  const wasActive = isActive(p);
  const kind = state as CardKind;
  if (state === "idle") {
    return { p: { ...p, card: { ...initial.card }, pendingConfirm: null, held: null }, newRun: false, continued: false, hide: true };
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
      pendingConfirm: kind === "confirm" ? p.pendingConfirm : null,
      held: kind === "confirm" ? p.held : null,
      followupUntil: newRun ? 0 : p.followupUntil,
      pausedLeft: null,
    },
    newRun,
    continued,
    hide: false,
  };
}

/** A confirm card was asked for: it must stay until answered. */
export function onConfirm(p: Presenter, requestId: string, runId: string | null): Presenter {
  return { ...p, card: { ...p.card, kind: "confirm", runId: runId ?? p.card.runId, fadeAt: null }, pendingConfirm: requestId };
}

/** The owner left (held) or came back: the waiting card is put aside, or shown again. Other cards are untouched. */
export function onConfirmHold(p: Presenter, requestId: string, held: boolean): Presenter {
  if (p.pendingConfirm !== requestId) return p;
  return { ...p, held: held ? requestId : null };
}

/** The waiting card is on screen (not put aside while the owner is away). */
export const confirmVisible = (p: Presenter): boolean => p.pendingConfirm !== null && p.held === null;

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
  if (a.runId && p.runId && a.runId !== p.runId && isActive(p)) return { p, shown: false };  // a late, stale answer
  const fadeAt = a.ms === null ? null : now + Math.max(a.ms, p.followupUntil > now ? p.followupUntil - now + 500 : 0);
  const thread = a.threadId ?? (a.kind === "notice" ? null : p.threadId);
  return {
    p: {
      ...p,
      card: { kind: a.kind, runId: a.runId ?? (a.kind === "notice" ? null : p.runId), threadId: thread, fadeAt },
      threadId: a.kind === "notice" ? p.threadId : thread,
      lastAnswer: a.summary && thread ? { threadId: thread, text: a.summary } : p.lastAnswer,
      pendingConfirm: null,
      held: null,
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
  if (p.history.length > HISTORY) out.push("too many earlier turns");
  if (p.history.some((t) => t.threadId !== p.threadId)) out.push("an earlier turn from another thread");
  return out;
}

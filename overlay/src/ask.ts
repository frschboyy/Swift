// Swift's question during a request (ADR-016 §5.1, ``ask``): shown on the working card while the
// request waits for the owner's answer. Said aloud first ("asking"), then the microphone (or the
// text box, for a typed request) takes the answer for ``seconds`` ("listening"); "again" after an
// answer Swift couldn't work out; "heard" while the answer is transcribed. Closed by the backend
// (``open: false``) once answered, or unanswered and put in the stack. An option clicked is an
// answer (``ask.reply``), never an approval.

export type AskPhase = "asking" | "listening" | "again" | "heard";

export type AskData = {
  ask_id: string;
  run_id: string;
  open: boolean;
  question?: string;
  kind?: string;
  options?: string[];
  thread_id?: string | null;
  phase?: AskPhase;
  // "again": the question as Swift says it once more ("Sorry, which one: Sam Lee or Sam Okoro?").
  text?: string;
  seconds?: number;
};

export type Ask = {
  id: string;
  runId: string;
  threadId: string | null;
  question: string;
  kind: string;
  options: string[];
  phase: AskPhase;
  // When the answer window closes (ms), or null while Swift is still saying it.
  until: number | null;
};

// More than this and the options are read, not clicked (the card has room for a row of buttons).
export const MAX_BUTTONS = 4;

/** The question on screen after an ``ask`` message (null: none). A close for another question leaves it. */
export function onAsk(cur: Ask | null, d: AskData, now: number): Ask | null {
  if (!d.open) return cur && cur.id === d.ask_id ? null : cur;
  const phase = d.phase ?? "listening";
  const same = cur?.id === d.ask_id ? cur : null;
  const question = phase === "again" && d.text ? d.text : d.question ?? same?.question ?? "";
  const timed = (phase === "listening" || phase === "again") && (d.seconds ?? 0) > 0;
  return {
    id: d.ask_id,
    runId: d.run_id,
    threadId: d.thread_id ?? same?.threadId ?? null,
    question,
    kind: d.kind ?? same?.kind ?? "free",
    options: d.options ?? same?.options ?? [],
    phase,
    until: timed ? now + (d.seconds as number) * 1000 : phase === "heard" ? null : same?.until ?? null,
  };
}

/** The answers offered as buttons: yes/no, or a short list of choices. Free text and values are said or typed. */
export function askButtons(a: Ask): string[] {
  if (a.kind === "yes_no") return ["Yes", "No"];
  if (a.kind === "choice" && a.options.length > 0 && a.options.length <= MAX_BUTTONS) return a.options;
  return [];
}

/** The pill under the question: what Swift is doing with it now. */
export function askPill(a: Ask, speaking: boolean): string {
  if (a.phase === "heard") return "Got it…";
  if (speaking || a.phase === "asking") return "Speaking… I'll listen when I'm done";
  return a.phase === "again" ? "Once more: waiting for your answer" : "Waiting for your answer";
}

/** Whether the question shows now: on the working card of its own request, the one in front. */
export function askVisible(a: Ask | null, state: string, focus: string | null): boolean {
  return a !== null && state === "working" && (focus === null || focus === a.runId);
}

/** Seconds left in the answer window (0: none, or over). */
export function askLeft(a: Ask, now: number): number {
  return a.until === null ? 0 : Math.max(0, Math.ceil((a.until - now) / 1000));
}

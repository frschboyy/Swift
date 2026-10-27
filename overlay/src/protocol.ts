// Mirror of src/swift/ipc/protocol.py (PLAN.md §3). Keep the two in sync.

export const PROTOCOL_VERSION = 1;

export type UiState =
  | "idle"
  | "listening"
  | "transcribing"
  | "working"
  | "confirm"
  | "result"
  | "error";

export type Scenario = "happy" | "confirm" | "error" | "long" | "email";
export const SCENARIOS: Scenario[] = ["happy", "confirm", "error", "long", "email"];

// Who is doing the work (ADR-008): a provider working for Swift. Absent or null: Swift itself.
export type Agent = { id: string; name: string };
// Normalized by the backend from each provider's own events (executors/base.py Activity).
export type Activity =
  | "starting" | "reading" | "searching" | "editing" | "running" | "browsing"
  | "delegating" | "planning" | "thinking" | "waiting" | "switching" | "blocked" | "working"
  // Swift's own, in the owner's app (ADR-012 §6): the step carries `app`.
  | "writing";

export type ResultDetails =
  | { kind: "text"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; columns: string[]; rows: string[][] };

// ADR-010: what a run is working on, as typed, versioned snapshots (swift/workflows/artifacts.py).
export type Phase = "resolving" | "drafting" | "confirming" | "sending" | "done" | "failed";
export type Person = { name: string; email: string };
// filled_in: the email is in Gmail's compose window or an Outlook draft; the owner presses Send (ADR-012 Q3).
export type SendState = "waiting_approval" | "sending" | "sent" | "failed" | "rejected" | "filled_in";
export type CalendarEventData = {
  title: string; when: string; location: string; all_day: boolean; start: string; end: string; state?: SendState; reason?: string;
  // Who is invited, and a Meet link asked for or present.
  attendees?: string; meet?: boolean;
  // A change: the event before it and the card's "before → after" lines. A removal: removing.
  before?: Omit<CalendarEventData, "before" | "changes">; changes?: string[]; removing?: boolean;
};
export type Artifact = { run_id: string; thread_id?: string; id: string; phase: Phase; version: number; title: string; agent?: Agent | null } & (
  | { kind: "email_draft"; data: { to: Person[]; subject: string; body: string } }
  | { kind: "recipient"; data: { query: string; candidates: (Person & { source: string; detail?: string })[]; chosen: number | null } }
  | { kind: "send_status"; data: { state: SendState; draft_id?: string; message_id?: string; reason?: string; app?: string } }
  | { kind: "calendar_event"; data: CalendarEventData }
  | { kind: "text" | "list" | "table"; data: ResultDetails }
);

export type Inbound =
  | { type: "hello.ok"; data: { version: string; debug: boolean; hotkeys: Record<string, string> } }
  | { type: "state"; data: { state: UiState; run_id?: string; agent?: Agent | null; thread_id?: string } }
  | { type: "level"; data: { rms: number } }
  | { type: "transcript"; data: { text: string; final: boolean } }
  | { type: "step"; data: { run_id: string; text: string; kind: string; ts: number; activity?: Activity; agent?: Agent | null; subagent?: boolean; thread_id?: string; app?: string | null } }
  // timeout_s: how long the card waits before the run stops without an answer.
  // artifact_id: the card shows that artifact (the draft for Swift's send_email card; agent is then null).
  | { type: "confirm.request"; data: { request_id: string; run_id: string; title: string; detail: string; tool: string; agent?: Agent | null; timeout_s?: number | null; artifact_id?: string | null; thread_id?: string } }
  // Push-to-talk on an open confirm card; the state stays "confirm".
  | { type: "confirm.voice"; data: { request_id: string; phase: "listening" | "transcribing" | "idle" | "hint" | "again"; text: string } }
  // note: Swift's own aside above the answer ("No, I'm Swift. ...").
  | { type: "result"; data: { run_id: string; status: "done" | "cancelled" | "error" | "rejected"; summary: string; details?: ResultDetails | null; agent?: Agent | null; note?: string | null; thread_id?: string } }
  // ADR-009: title/message/hint are written for the owner; detail is the raw text, shown on request.
  // retry: "Try again" re-runs the request. severity "info": a nudge, not a failure.
  | { type: "error"; data: ErrorData }
  | { type: "artifact"; data: Artifact }
  // Open the detail view on an artifact (null: the steps), or close it. Swift decides which (ADR-010 §7).
  | { type: "view"; data: { run_id: string; artifact_id: string | null; open: boolean } }
  // Push-to-talk while working: the mid-run grammar ("show me", "stop").
  | { type: "run.voice"; data: { run_id: string; phase: "listening" | "transcribing" | "idle" | "hint"; text: string } }
  // After an answer, the open mic takes a reply without the wake phrase for `seconds` (wake listening on).
  // question: the answer asked something, so the window is longer and the card says "your answer".
  | { type: "followup"; data: { open: boolean; seconds: number; question?: boolean } }
  // Whether the owner is here and whether hands-free listening is on, and why not (ADR-014 §8).
  | { type: "presence"; data: { state: "here" | "idle" | "away"; reason: string; listening: boolean; wake: boolean } }
  // ADR-014 §4: the owner is away, so the confirm card is put aside (hidden, its countdown stopped);
  // held false: they're back, and the card has timeout_s left.
  | { type: "confirm.hold"; data: { request_id: string; held: boolean; timeout_s: number } }
  // ADR-014 §5: after an answer, one line naming a conversation left unfinished ("continue" picks it up).
  | { type: "resume.offer"; data: { thread_id: string; title: string } }
  // ADR-013 phase B: the request in front, the others as one-line rows, and cards waiting behind the one shown.
  | { type: "runs"; data: { focus: string | null; rows: RunRow[]; waiting: number } }
  // Swift heard its name or the hotkey, before transcribing anything: the "Listening…" pulse (heard.ts).
  | { type: "heard"; data: { source: "wake" | "ptt" | "queued"; text: string } };

export type RunRow = {
  run_id: string;
  thread_id: string | null;
  title: string;
  state: string;
  activity: Activity | null;
  app: string | null;
  agent: Agent | null;
  started_ms: number;
  summary: string;
};

export type ErrorData = {
  code: string;
  message: string;
  hint: string;
  title?: string | null;
  detail?: string | null;
  retry?: boolean;
  severity?: "error" | "info";
  agent?: Agent | null;
  thread_id?: string;
};

export type Outbound =
  | { type: "hello"; data: { token: string; client: string } }
  | { type: "ptt"; data: { state: "down" | "up" } }
  | { type: "cancel"; data: Record<string, never> }
  | { type: "retry"; data: Record<string, never> }
  | { type: "confirm.reply"; data: { request_id: string; decision: "approve" | "reject" } }
  | { type: "debug.run"; data: { scenario: Scenario } }
  | { type: "debug.ask"; data: { text: string } }
  | { type: "debug.say"; data: { text: string } }
  // The card's Show / Back button: the same as saying "show me" / "hide that".
  | { type: "view"; data: { action: "show" | "hide" } }
  // A background request to the front: a row clicked, or the card in front gone while it runs.
  | { type: "focus"; data: { run_id: string } }
  // A confirm card is drawn and visible, or hidden again: its countdown runs only while it is (ADR-015 §4.2).
  | { type: "card.seen"; data: { request_id: string; visible: boolean } }
  | { type: "ready"; data: { startup_ms: number; backend_ms: number | null } };

export function encode(msg: Outbound): string {
  return JSON.stringify({ v: PROTOCOL_VERSION, type: msg.type, ts: Date.now(), data: msg.data });
}

export function decode(raw: string): Inbound | null {
  try {
    const obj = JSON.parse(raw);
    if (obj?.v !== PROTOCOL_VERSION || typeof obj.type !== "string" || typeof obj.data !== "object") return null;
    return { type: obj.type, data: obj.data } as Inbound;
  } catch {
    return null;
  }
}

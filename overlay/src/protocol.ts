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

export type Scenario = "happy" | "confirm" | "error" | "long";
export const SCENARIOS: Scenario[] = ["happy", "confirm", "error", "long"];

// Who is doing the work (ADR-008): a provider working for Swift. Absent or null: Swift itself.
export type Agent = { id: string; name: string };
// Normalized by the backend from each provider's own events (executors/base.py Activity).
export type Activity =
  | "starting" | "reading" | "searching" | "editing" | "running" | "browsing"
  | "delegating" | "planning" | "thinking" | "waiting" | "switching" | "blocked" | "working";

export type ResultDetails =
  | { kind: "text"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; columns: string[]; rows: string[][] };

export type Inbound =
  | { type: "hello.ok"; data: { version: string; debug: boolean; hotkeys: Record<string, string> } }
  | { type: "state"; data: { state: UiState; run_id?: string; agent?: Agent | null } }
  | { type: "level"; data: { rms: number } }
  | { type: "transcript"; data: { text: string; final: boolean } }
  | { type: "step"; data: { run_id: string; text: string; kind: string; ts: number; activity?: Activity; agent?: Agent | null; subagent?: boolean } }
  // timeout_s: how long the card waits before the run stops without an answer.
  | { type: "confirm.request"; data: { request_id: string; run_id: string; title: string; detail: string; tool: string; agent?: Agent | null; timeout_s?: number | null } }
  // Push-to-talk on an open confirm card; the state stays "confirm".
  | { type: "confirm.voice"; data: { request_id: string; phase: "listening" | "transcribing" | "idle" | "hint"; text: string } }
  // note: Swift's own aside above the answer ("No, I'm Swift. ...").
  | { type: "result"; data: { run_id: string; status: "done" | "cancelled" | "error" | "rejected"; summary: string; details?: ResultDetails | null; agent?: Agent | null; note?: string | null } }
  // ADR-009: title/message/hint are written for the owner; detail is the raw text, shown on request.
  // retry: "Try again" re-runs the request. severity "info": a nudge, not a failure.
  | { type: "error"; data: ErrorData };

export type ErrorData = {
  code: string;
  message: string;
  hint: string;
  title?: string | null;
  detail?: string | null;
  retry?: boolean;
  severity?: "error" | "info";
  agent?: Agent | null;
};

export type Outbound =
  | { type: "hello"; data: { token: string; client: string } }
  | { type: "ptt"; data: { state: "down" | "up" } }
  | { type: "cancel"; data: Record<string, never> }
  | { type: "retry"; data: Record<string, never> }
  | { type: "confirm.reply"; data: { request_id: string; decision: "approve" | "reject" } }
  | { type: "debug.run"; data: { scenario: Scenario } }
  | { type: "debug.ask"; data: { text: string } }
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

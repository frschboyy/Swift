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

export type ResultDetails =
  | { kind: "text"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; columns: string[]; rows: string[][] };

export type Inbound =
  | { type: "hello.ok"; data: { version: string; debug: boolean; hotkeys: Record<string, string> } }
  | { type: "state"; data: { state: UiState; run_id?: string } }
  | { type: "level"; data: { rms: number } }
  | { type: "transcript"; data: { text: string; final: boolean } }
  | { type: "step"; data: { run_id: string; text: string; kind: string; ts: number } }
  | { type: "confirm.request"; data: { request_id: string; run_id: string; title: string; detail: string; tool: string } }
  | { type: "result"; data: { run_id: string; status: "done" | "cancelled" | "error" | "rejected"; summary: string; details?: ResultDetails | null } }
  | { type: "error"; data: { code: string; message: string; hint: string } };

export type Outbound =
  | { type: "hello"; data: { token: string; client: string } }
  | { type: "ptt"; data: { state: "down" | "up" } }
  | { type: "cancel"; data: Record<string, never> }
  | { type: "confirm.reply"; data: { request_id: string; decision: "approve" | "reject" } }
  | { type: "debug.run"; data: { scenario: Scenario } }
  | { type: "debug.ask"; data: { text: string } };

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

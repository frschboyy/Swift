// Dev only: replay message sequences into the overlay (ADR-013 §6), to check by eye what the
// presenter tests check by rule. Uses __shim.inject, so no backend request is made.

type Shim = { inject: (type: string, data: Record<string, unknown>) => boolean };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const AGENT = { id: "claude_code", name: "Claude Code" };

async function correctionAfterReject(s: Shim): Promise<void> {
  // The 2026-10-26 sequence: rejected, a correction in the reply window, a new card.
  s.inject("state", { state: "result", run_id: "r1", agent: AGENT, thread_id: "t1" });
  s.inject("result", { run_id: "r1", status: "rejected", summary: "The meeting with Mr. Akande wasn't added.", details: null, agent: AGENT, note: null, thread_id: "t1" });
  s.inject("followup", { open: true, seconds: 8 });
  await sleep(2500);
  s.inject("followup", { open: false, seconds: 0 });
  s.inject("transcript", { text: "Make it Wednesday at 8 pm instead", final: true });
  s.inject("state", { state: "working", run_id: "r2", agent: AGENT, thread_id: "t1" });
  s.inject("step", { run_id: "r2", text: "Thinking it over", kind: "tool", ts: Date.now(), activity: "thinking", agent: AGENT, subagent: false, thread_id: "t1" });
  await sleep(1500);
  s.inject("state", { state: "confirm", run_id: "r2", agent: AGENT, thread_id: "t1" });
  s.inject("confirm.request", { request_id: "swift:2", run_id: "r2", title: "Add to your calendar: Meeting with Mr. Akande", detail: "Wed 28 Oct 2026, 20:00–21:00", tool: "create_calendar_event", agent: null, timeout_s: 120, artifact_id: null, thread_id: "t1" });
}

async function threeTurnThread(s: Shim): Promise<void> {
  // Follow-ups continue one card: earlier answers shrink to a line above it.
  for (const [i, [q, a]] of [["What time is it?", "It's 19:42."], ["And the date?", "It's Monday, 26 October 2026."], ["Anything on my calendar tonight?", "Nothing after 18:00."]].entries()) {
    s.inject("transcript", { text: q, final: true });
    s.inject("state", { state: "working", run_id: `q${i}`, agent: AGENT, thread_id: "t9" });
    await sleep(900);
    s.inject("state", { state: "result", run_id: `q${i}`, agent: AGENT, thread_id: "t9" });
    s.inject("result", { run_id: `q${i}`, status: "done", summary: a, details: null, agent: AGENT, note: null, thread_id: "t9" });
    s.inject("followup", { open: true, seconds: 8 });
    await sleep(2200);
  }
}

const SCENARIOS: Record<string, (s: Shim) => Promise<void>> = { correctionAfterReject, threeTurnThread };

(window as unknown as Record<string, unknown>).__replay = (name: string): Promise<void> | undefined => {
  const shim = (window as unknown as { __shim: Shim }).__shim;
  return SCENARIOS[name]?.(shim);
};

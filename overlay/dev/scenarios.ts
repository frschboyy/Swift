// Dev only: replay message sequences into the overlay (ADR-013 §6), to check by eye what the
// presenter tests check by rule. Uses __shim.inject, so no backend request is made.
//
// ADR-017: every state of the Capsule design, one call each: ``__design("confirmAdd")`` (or the
// harness's "Design state" list). ``__design.list`` names them. Each starts from rest. The pane
// windows' states (chips, stack, typing box, tray menu) are drawn by dev/pane.html.

type Shim = {
  inject: (type: string, data: Record<string, unknown>) => boolean;
  emit: (event: string, payload: unknown) => void;
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const AGENT = { id: "claude_code", name: "Claude" };

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

// ---- ADR-017: the Capsule design's states --------------------------------------------------------

let n = 0;
const run = (): string => `d${++n}`;
const HERE = { state: "here", reason: "input", listening: true, wake: true, paused: false };

/** Back to rest: no card, no chips, no stack, listening, not speaking. */
async function reset(s: Shim): Promise<void> {
  s.inject("speech", { speaking: false });
  s.inject("followup", { open: false, seconds: 0 });
  s.inject("presence", HERE);
  s.inject("runs", { focus: null, rows: [], waiting: 0 });
  s.inject("stack", { items: [] });
  s.inject("state", { state: "idle" });
  await sleep(260);
}

/** A request said and answered: transcript, working, then the result. */
async function answer(s: Shim, words: string, summary: string, details: unknown = null, opts: { typed?: boolean; agent?: unknown; artifacts?: unknown[] } = {}): Promise<string> {
  const id = run();
  s.inject("transcript", { text: words, final: true, typed: !!opts.typed });
  s.inject("state", { state: "working", run_id: id, agent: opts.agent ?? AGENT, thread_id: `t-${id}` });
  for (const a of opts.artifacts ?? []) s.inject("artifact", { ...(a as object), run_id: id });
  s.inject("state", { state: "result", run_id: id, agent: opts.agent ?? AGENT, thread_id: `t-${id}` });
  s.inject("result", { run_id: id, status: "done", summary, details, agent: opts.agent ?? AGENT, note: null, thread_id: `t-${id}` });
  await sleep(220);
  return id;
}

const LONG = [
  "Tea began in southwest China, where leaves of *Camellia sinensis* were boiled as medicine as early as the Shang dynasty.",
  "Under the Tang it became a daily drink. Lu Yu wrote *The Classic of Tea* around 760 CE, setting out how to grow, prepare and serve it, and **powdered tea** whisked in bowls spread to Japan with Buddhist monks.",
  "The Song refined it further; the Ming switched to loose leaves steeped in pots, which is how most of the world drinks it now.",
  "Dutch and Portuguese traders brought it to Europe in the early 1600s. In Britain it was first a luxury for the court, then, as taxes fell in the 1780s, an everyday drink.",
  "To break China's hold on the trade, the East India Company grew tea in Assam and later Ceylon; by 1900 most British tea came from there.",
].join("\n\n");

const CALENDAR = { kind: "table", columns: ["Time", "What", "Where"], rows: [["9:00", "Design review", "Teams"], ["12:30", "Lunch with Sam Okafor", "Café Nord"], ["14:00", "Dentist", "Kirkgate 4"]] };

const EVENT = {
  title: "Meeting with Sam Okafor", when: "Fri 30 Oct, 16:00–17:00", location: "", all_day: false, start: "2026-10-30T16:00", end: "2026-10-30T17:00",
  attendees: "sam.okafor@northwind.com", meet: true, state: "waiting_approval",
};

async function confirm(s: Shim, title: string, artifact: Record<string, unknown> | null, detail = "", words = "Set up a meeting with Sam on Friday at four"): Promise<void> {
  const id = run();
  s.inject("transcript", { text: words, final: true, typed: false });
  s.inject("state", { state: "working", run_id: id, agent: AGENT, thread_id: `t-${id}` });
  if (artifact) s.inject("artifact", { run_id: id, thread_id: `t-${id}`, id: `a-${id}`, phase: "confirming", version: 1, title, agent: null, ...artifact });
  s.inject("state", { state: "confirm", run_id: id, agent: AGENT, thread_id: `t-${id}` });
  s.inject("confirm.request", {
    request_id: `swift:${id}`, run_id: id, title, detail, tool: "create_calendar_event", agent: null, timeout_s: 45,
    artifact_id: artifact ? `a-${id}` : null, thread_id: `t-${id}`,
  });
  await sleep(1300);  // a few seconds into the countdown: "0:43"
}

async function question(s: Shim, speaking: boolean): Promise<void> {
  const id = await answer(s, "Add lunch with Sam next week", "Which day and time works for you?");
  void id;
  if (speaking) {
    s.inject("speech", { speaking: true });
    s.inject("followup", { open: true, seconds: 25, question: true });
  } else {
    s.inject("followup", { open: true, seconds: 25, question: true });
    s.inject("speech", { speaking: false });
    await sleep(6500);  // into the window: "0:18"
  }
  await sleep(100);
}

const STACK = [
  { id: "card:swift:1", kind: "later", title: "Add lunch with Sam Okafor at Café Nord on Thursday at half past twelve", reason: "expired", since_ms: Date.now() - 4 * 60_000, thread_id: "t1" },
  { id: "parked:t2", kind: "parked", title: "Which day and time works for you for the design review?", reason: "asked", since_ms: Date.now() - 12 * 60_000, thread_id: "t2" },
  { id: "parked:t3", kind: "parked", title: "Draft an email to Priya about the tea report", reason: "stopped", since_ms: Date.now() - 65 * 60_000, thread_id: "t3" },
];

async function concurrent(s: Shim): Promise<void> {
  s.inject("transcript", { text: "Research the history of coffee and summarise it", final: true });
  s.inject("state", { state: "working", run_id: "front", agent: AGENT, thread_id: "tf" });
  s.inject("step", { run_id: "front", text: "Searching the web", kind: "tool", ts: Date.now(), activity: "searching", agent: AGENT, subagent: false, thread_id: "tf" });
  const now = Date.now();
  s.inject("runs", { focus: "front", waiting: 0, rows: [
    { run_id: `c1-${run()}`, thread_id: "t1", title: "Green tea research", state: "working", activity: "reading", app: null, agent: AGENT, started_ms: now - 96_000, summary: "", words: "Look up green tea research" },
    { run_id: `c2-${run()}`, thread_id: "t2", title: "Email to Priya", state: "confirm", activity: null, app: null, agent: null, started_ms: now - 40_000, summary: "", words: "Email Priya the tea report" },
    { run_id: `c3-${run()}`, thread_id: "t3", title: "Tea history", state: "result", activity: null, app: null, agent: AGENT, started_ms: now - 200_000, summary: "Tea began in China.", words: "Tea history" },
  ] });
  await sleep(300);
}

const DESIGN: Record<string, (s: Shim) => Promise<void>> = {
  // 1. the capsule
  capsuleIdle: async () => {},
  capsuleHeard: async (s) => { s.inject("heard", { source: "wake", text: "Listening…" }); await sleep(150); },
  capsuleListening: async (s) => {
    s.inject("state", { state: "listening" });
    s.inject("transcript", { text: "what's on my calendar tomorrow", final: false });
    for (let i = 0; i < 12; i++) { s.inject("level", { rms: 0.25 + 0.2 * Math.sin(i) }); await sleep(33); }
  },
  capsuleTranscribing: async (s) => {
    s.inject("state", { state: "listening" });
    s.inject("transcript", { text: "what's on my calendar tomorrow", final: false });
    s.inject("state", { state: "transcribing" });
    await sleep(150);
  },
  capsuleCantHear: async (s) => {
    s.inject("state", { state: "listening" });
    for (let i = 0; i < 44; i++) { s.inject("level", { rms: 0.01 }); await sleep(100); }
  },
  capsuleWorking: async (s) => {
    s.inject("transcript", { text: "Research the history of coffee", final: true });
    s.inject("state", { state: "working", run_id: run(), agent: AGENT, thread_id: "tw" });
    await sleep(150);
  },
  capsuleSpeaking: async (s) => { await answer(s, "What time is it?", "It's 3:42 pm"); s.inject("speech", { speaking: true }); await sleep(150); },
  pausedMic: async (s) => { s.inject("presence", { ...HERE, listening: false, paused: true }); await sleep(150); },
  pausedLocked: async (s) => { s.inject("presence", { state: "here", reason: "locked", listening: false, wake: true, paused: false }); await sleep(150); },
  // 2. the main card
  working: async (s) => {
    const id = run();
    s.inject("transcript", { text: "Research the history of coffee and write a summary in Word", final: true });
    s.inject("state", { state: "working", run_id: id, agent: AGENT, thread_id: `t-${id}` });
    for (const [text, activity] of [["Searched the web", "searching"], ["Read 5 pages", "reading"], ["Writing the summary", "writing"]]) {
      s.inject("step", { run_id: id, text, kind: "tool", ts: Date.now(), activity, agent: AGENT, subagent: false, thread_id: `t-${id}`, app: "Word" });
    }
    await sleep(3400);  // elapsed shows after 3 s
  },
  answerLine: async (s) => { await answer(s, "What time is it?", "It's 3:42 pm"); },
  answerText: async (s) => { await answer(s, "Is it going to rain this afternoon?", "Probably not. There's a 20% chance of a light shower around 4 pm, then it clears. 14 °C at the warmest."); },
  answerTable: async (s) => { await answer(s, "What's on my calendar tomorrow?", "Three things on Thursday, 29 October. Free after 3 pm.", CALENDAR); },
  answerTyped: async (s) => { await answer(s, "convert 12 miles to km", "12 miles is **19.3 km**.", null, { typed: true }); },
  answerLong: async (s) => { await answer(s, "Give me a short history of tea", LONG); },
  answerLongOpen: async (s) => {
    await answer(s, "Give me a short history of tea", LONG);
    document.querySelector<HTMLButtonElement>("#card .card-foot .link")?.click();
    await sleep(250);
  },
  failed: async (s) => {
    s.inject("transcript", { text: "Email the tea report to Priya", final: true });
    s.inject("state", { state: "working", run_id: run(), agent: AGENT, thread_id: "tfail" });
    s.inject("state", { state: "error", run_id: `d${n}`, agent: AGENT, thread_id: "tfail" });
    s.inject("error", { code: "service", title: "Couldn't send the email", message: "Outlook didn't respond. Nothing was sent.", hint: "", detail: "HTTP 503 from graph.microsoft.com/v1.0/me/sendMail (request id 7f3c…)", retry: true, severity: "error", agent: null, thread_id: "tfail" });
    await sleep(200);
  },
  failedDetails: async (s) => {
    await DESIGN.failed(s);
    document.querySelector<HTMLButtonElement>("#card .link")?.click();
    await sleep(150);
  },
  cancelled: async (s) => {
    const id = run();
    s.inject("transcript", { text: "Summarise the coffee history", final: true });
    s.inject("state", { state: "working", run_id: id, agent: AGENT, thread_id: `t-${id}` });
    s.inject("state", { state: "result", run_id: id, agent: AGENT, thread_id: `t-${id}` });
    s.inject("result", { run_id: id, status: "cancelled", summary: "Cancelled", details: null, agent: AGENT, note: null, thread_id: `t-${id}` });
    await sleep(200);
  },
  notApproved: async (s) => {
    const id = run();
    s.inject("state", { state: "result", run_id: id, agent: null, thread_id: `t-${id}` });
    s.inject("result", { run_id: id, status: "rejected", summary: "You rejected the email to Priya", details: null, agent: null, note: null, thread_id: `t-${id}` });
    await sleep(200);
  },
  // 3. confirm
  confirmAdd: async (s) => { await confirm(s, "Add to your calendar", { kind: "calendar_event", data: EVENT }); },
  confirmChange: async (s) => {
    await confirm(s, "Move “Design review”", { kind: "calendar_event", data: {
      ...EVENT, title: "Design review", when: "Fri 30 Oct, 11:00–12:00", attendees: "4 invitees", meet: false,
      before: { title: "Design review", when: "Thu 29 Oct, 9:00–10:00", location: "", all_day: false, start: "", end: "", attendees: "4 invitees" },
      changes: ["4 invitees, unchanged · they'll get an update"],
    } }, "", "Move the design review to Friday at eleven");
  },
  confirmEmail: async (s) => {
    await confirm(s, "Send this email", { kind: "email_draft", data: {
      to: [{ name: "Priya Raman", email: "priya@contoso.com" }], subject: "Tea report, first draft",
      body: "Hi Priya, here's the first draft of the tea report. The history section is done; I'd love your notes on the trade figures before Friday.\n\nThanks,\nFrancis",
    } }, "", "Email Priya the tea report");
  },
  confirmCommand: async (s) => { await confirm(s, "Run a command in your project", null, "npm run build -- --mode production", "Build the site"); },
  confirmAway: async (s) => {
    await DESIGN.confirmChange(s);
    s.inject("presence", { ...HERE, state: "idle", reason: "idle" });
    await sleep(150);
  },
  // 4. Swift's question
  questionSpeaking: async (s) => { await question(s, true); },
  questionWaiting: async (s) => { await question(s, false); },
  // 5. several requests (the harness draws the chips under the card)
  concurrent: async (s) => { await concurrent(s); },
  // 6. the stack (inline in the harness)
  stackClosed: async (s) => { s.inject("stack", { items: STACK }); await sleep(150); },
  stackOpen: async (s) => {
    s.inject("stack", { items: STACK });
    await sleep(100);
    const top = document.querySelector<HTMLElement>("#stack .stack");
    top?.click();
    top?.click();
    await sleep(250);
  },
  // 8. timers and reminders
  timerDue: async (s) => {
    s.inject("state", { state: "result", run_id: "due-timer-7", agent: null });
    s.inject("result", { run_id: "due-timer-7", status: "done", summary: "Your tea timer is up.", details: null, agent: null, note: null });
    await sleep(200);
  },
  reminderDue: async (s) => {
    s.inject("state", { state: "result", run_id: "due-reminder-3", agent: null });
    s.inject("result", { run_id: "due-reminder-3", status: "done", summary: "Reminder: call mum.", details: null, agent: null, note: null });
    await sleep(200);
  },
  // 11. the live view of a running request (ADR-017 §7): research, then writing it into Word
  liveResearch: async (s) => { await liveResearch(s, false); },
  liveDone: async (s) => { await liveResearch(s, true); },
};

async function liveResearch(s: Shim, end: boolean): Promise<void> {
  const id = run();
  const live = (d: Record<string, unknown>) => s.inject("live", { run_id: id, ...d });
  const step = (text: string, activity: string, app: string | null = null) => {
    s.inject("step", { run_id: id, text, kind: "tool", ts: Date.now(), activity, agent: AGENT, subagent: false, app });
    live({ kind: "doing", text, activity, app });
  };
  s.inject("transcript", { text: "Research the history of tea and write it into Word", final: true });
  s.inject("state", { state: "working", run_id: id, agent: AGENT });
  step("Searching the web: history of tea", "searching");
  for (const [title, url] of [
    ["Tea | Origin, History, Types, & Facts", "https://www.britannica.com/topic/tea-beverage"],
    ["History of tea - Wikipedia", "https://en.wikipedia.org/wiki/History_of_tea"],
    ["Tea History: Ancient China to the West", "https://www.teaclass.com/lesson_0102.html"],
  ]) live({ kind: "source", url, title, state: "found" });
  s.inject("watch", { run_id: id, open: true, title: "Research the history of tea", words: "" });
  await sleep(150);
  step("Fetching britannica.com", "browsing");
  live({ kind: "source", url: "https://www.britannica.com/topic/tea-beverage", state: "read" });
  live({ kind: "source", url: "https://en.wikipedia.org/wiki/History_of_tea", state: "reading" });
  live({ kind: "note", text: "Tea was first drunk in south-west China, in Yunnan, as a medicinal drink." });
  live({ kind: "note", text: "It reached Europe through Portuguese and Dutch traders in the 16th and 17th centuries." });
  step("Writing in Word", "writing", "Word");
  for (const text of ["The history of tea", "", "Tea began in south-west China, where it was drunk as a medicine long before it became an everyday drink.",
    "By the Tang dynasty it was traded across the empire, pressed into bricks.", "Portuguese and Dutch ships brought it to Europe."]) {
    live({ kind: "text", text, app: "Word" });
    await sleep(60);
  }
  if (!end) return;
  live({ kind: "source", url: "https://en.wikipedia.org/wiki/History_of_tea", state: "read" });
  s.inject("state", { state: "result", run_id: id, agent: AGENT });
  s.inject("result", { run_id: id, status: "done", summary: "I wrote a one-page history of tea into your Word document: its start in China, the Tang trade and how it reached Europe.", details: null, agent: AGENT, note: null });
  await sleep(150);
}

const design = async (name: string): Promise<void> => {
  const shim = (window as unknown as { __shim: Shim }).__shim;
  const step = DESIGN[name];
  if (!step) throw new Error(`no design state ${name}; try one of ${Object.keys(DESIGN).join(", ")}`);
  await reset(shim);
  await step(shim);
};
design.list = Object.keys(DESIGN);
(window as unknown as Record<string, unknown>).__design = design;

// The harness's "Design state" list.
const select = document.getElementById("design") as HTMLSelectElement | null;
for (const name of design.list) select?.append(new Option(name, name));

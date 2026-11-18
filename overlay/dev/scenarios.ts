// Dev only: replay message sequences into the overlay (ADR-013 §6), to check by eye what the
// presenter tests check by rule. Uses __shim.inject, so no backend request is made.
//
// ADR-017: every state of the Capsule design, one call each: ``__design("confirmAdd")`` (or the
// harness's "Design state" list). ``__design.list`` names them. Each starts from rest. The pane
// windows' states (stack, typing box, tray menu) are drawn by dev/pane.html.

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
  s.inject("confirm.request", { request_id: "swift:2", run_id: "r2", title: "Add to your calendar: Meeting with Mr. Akande", detail: "Wed 28 Oct 2026, 20:00–21:00", tool: "create_calendar_event", agent: null, artifact_id: null, thread_id: "t1" });
  s.inject("countdown", { request_id: "swift:2", left_s: 120, running: true });
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

/** Back to rest: no card, no edges, no stack, listening, not speaking. */
const notice = (name: string): void => (window as unknown as { __overlay: { notice: (n: string) => void } }).__overlay.notice(name);

async function reset(s: Shim): Promise<void> {
  s.inject("speech", { speaking: false });
  s.inject("followup", { open: false, seconds: 0 });
  s.inject("presence", HERE);
  s.inject("runs", { focus: null, rows: [], waiting: 0 });
  s.inject("stack", { items: [] });
  s.inject("timers", { items: [] });
  s.inject("state", { state: "idle" });
  await sleep(260);
}

/** A request said and answered: transcript, working, then the result. */
async function answer(s: Shim, words: string, summary: string, details: unknown = null, opts: { typed?: boolean; agent?: unknown; artifacts?: unknown[]; caveat?: string } = {}): Promise<string> {
  const id = run();
  s.inject("transcript", { text: words, final: true, typed: !!opts.typed });
  s.inject("state", { state: "working", run_id: id, agent: opts.agent ?? AGENT, thread_id: `t-${id}` });
  for (const a of opts.artifacts ?? []) s.inject("artifact", { ...(a as object), run_id: id });
  s.inject("state", { state: "result", run_id: id, agent: opts.agent ?? AGENT, thread_id: `t-${id}` });
  s.inject("result", { run_id: id, status: "done", summary, details, agent: opts.agent ?? AGENT, note: null, thread_id: `t-${id}`, ...(opts.caveat ? { caveat: opts.caveat } : {}) });
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

// B4: a comparison as swift/shapes.py hands it on (checked, sized, marked as the worker's).
const LAPTOPS = {
  kind: "compare", title: "Laptops for travel", items: ["Zenbook 14", "XPS 13", "Swift Go 14"], pick: 0, by: "worker", size: "card",
  rows: [{ label: "Weight", values: ["1.2 kg", "1.2 kg", "1.3 kg"] }, { label: "Battery", values: ["15 h", "12 h", "10 h"] },
    { label: "Screen", values: ['14" OLED', '13.4" IPS', '14" OLED'] }, { label: "Price", values: ["$1,099", "$1,299", "$899"] }],
};

// B4: diagrams as swift/shapes.py hands them on; the last one doesn't parse, so the card keeps the words.
const FLOW = {
  kind: "diagram", title: "How a request runs", by: "worker", size: "card",
  source: "flowchart TD\n  A[You ask] --> B{Needs your OK?}\n  B -->|no| D[Done]\n  B -->|yes| C[Card]\n  C -->|approved| D\n  C -->|declined| E[Stopped]",
};
// The same flow left to right: too wide to read shrunk into a card, so it opens with Read more (as does the one
// above, too tall); a small one that fits.
const FLOW_WIDE = { ...FLOW, source: FLOW.source.replace("flowchart TD", "flowchart LR") };
const FLOW_SMALL = { ...FLOW, title: "Asking for your OK", source: "flowchart LR\n  A[You ask] --> B{OK?}\n  B -->|yes| C[Done]\n  B -->|no| D[Stopped]" };
const SEQUENCE = {
  kind: "diagram", title: "Signing in", by: "worker", size: "expanded",
  source: "sequenceDiagram\n  participant You\n  participant Swift\n  participant Google\n  You->>Swift: Sign in\n  Swift->>Google: Open the sign-in page\n  Google-->>You: Ask for your password\n  You->>Google: Approve\n  Google-->>Swift: A token\n  Swift-->>You: Signed in",
};
// B4: a mind map as swift/shapes.py hands it on; the second has more ideas than a card shows.
const PARTY = {
  kind: "mindmap", title: "Party ideas", root: "Birthday party", by: "worker", size: "card",
  children: [
    { label: "Games", children: [{ label: "Treasure hunt", children: [] }, { label: "Musical chairs", children: [] }] },
    { label: "Food", children: [{ label: "Pizza", children: [] }, { label: "A cake shaped like a dinosaur", children: [{ label: "Order by Thursday", children: [] }] }] },
    { label: "Invites", children: [{ label: "Class of 24", children: [] }] },
    { label: "Music", children: [] },
  ],
};
// A big first branch: the card still shows every branch (taken level by level), then the first ideas under them.
const PARTY_BIG = { ...PARTY, size: "expanded", children: [
  { label: "Games", children: ["Treasure hunt", "Musical chairs", "Pass the parcel", "Sack race", "Limbo", "Charades"].map((label) => ({ label, children: [] })) },
  ...PARTY.children.slice(1), { label: "Decorations", children: ["Balloons", "Bunting", "Fairy lights"].map((label) => ({ label, children: [] })) }] };
const samplePdfPage = (): string => {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 720;
  const g = canvas.getContext("2d");
  if (!g) return "";
  g.fillStyle = "#fff";
  g.fillRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = "#334155";
  g.font = "bold 24px sans-serif";
  g.fillText("Project brief", 28, 52);
  g.fillStyle = "#94a3b8";
  for (let y = 94; y < 680; y += 28) g.fillRect(28, y, y % 3 ? 440 : 300, 2);
  return canvas.toDataURL("image/png").split(",", 2)[1] ?? "";
};
const PDF_PREVIEW = {
  kind: "preview", path: "C:\\Users\\owner\\Documents\\project-brief.pdf", title: "project-brief.pdf",
  file_type: "pdf", thumbnail: samplePdfPage(), pages: 8, excerpt: null, by: "swift", size: "card",
};
const OFFICE_PREVIEW = {
  kind: "preview", path: "C:\\Users\\owner\\Documents\\plan.docx", title: "plan.docx", file_type: "docx",
  thumbnail: null, pages: null,
  excerpt: "This proposal compares three approaches, summarizes the constraints, and recommends a phased rollout. "
    .repeat(4),
  by: "swift", size: "expanded",
};
const CHART = {
  kind: "chart", title: "Quarterly active users", type: "bar", x: ["Q1", "Q2", "Q3", "Q4"],
  series: [{ name: "North", values: [12, 18, 15, 21] }, { name: "South", values: [9, 14, 17, 16] }],
  unit: "thousands", by: "worker", size: "card",
};
const CHART_LONG = {
  ...CHART, title: "Weekly active users", type: "line", size: "expanded",
  x: ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7", "Week 8"],
  series: [{ name: "North", values: [10, 12, 11, 15, 16, 15, 19, 21] },
    { name: "South", values: [8, 9, 13, 12, 14, 15, 15, 18] }],
};
const PROJECTS = {
  kind: "cards", title: "Current projects", by: "worker", size: "card",
  cards: [
    { title: "Website refresh", detail: "Update the homepage and simplify navigation.", meta: "Planning" },
    { title: "Data migration", detail: "Move the archive to the new storage service.", meta: "In progress" },
    { title: "Mobile app", detail: "Improve offline access and startup time.", meta: "Next quarter" },
  ],
};
const PROJECTS_LONG = {
  ...PROJECTS, size: "expanded",
  cards: [...PROJECTS.cards, { title: "Reporting", detail: "Combine project metrics in one dashboard.", meta: "Discovery" },
    { title: "Support portal", detail: "Make the help articles easier to find.", meta: "Planned" }],
};
const BROKEN = { kind: "diagram", title: "Half a flow", by: "worker", size: "card", source: "flowchart LR\n  A --> (((", text: "The steps: ask, check, answer." };

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
    request_id: `swift:${id}`, run_id: id, title, detail, tool: "create_calendar_event", agent: null,
    artifact_id: artifact ? `a-${id}` : null, thread_id: `t-${id}`,
  });
  s.inject("countdown", { request_id: `swift:${id}`, left_s: 45, running: true });
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

/** Past "Got it" (deck.ts ACK_MS), so the edges show what they are doing. */
const SETTLED_MS = 2700;
/** Three requests behind the card, all started a while ago. */
const behind = (): Record<string, unknown>[] => {
  const now = Date.now();
  return [
    { run_id: `c1-${run()}`, thread_id: "t1", title: "Green tea research", state: "working", activity: "reading", app: null, agent: AGENT, started_ms: now - 96_000, summary: "", words: "Look up green tea research" },
    { run_id: `c2-${run()}`, thread_id: "t2", title: "Email to Priya", state: "confirm", activity: null, app: null, agent: null, started_ms: now - 40_000, summary: "", words: "Email Priya the tea report" },
    { run_id: `c3-${run()}`, thread_id: "t3", title: "Tea history", state: "result", activity: null, app: null, agent: AGENT, started_ms: now - 200_000, summary: "Tea began in China.", words: "Tea history" },
  ];
};

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
  // A6: captions on, the speaking pill shows the words being said.
  capsuleCaptions: async (s) => {
    await answer(s, "What's the weather like?", "Light rain until four, then dry and 14 degrees.");
    s.inject("speech", { speaking: true, text: "Light rain until four, then dry and fourteen degrees." });
    await sleep(150);
  },
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
  // Board 9 §5: the reply window after an answer, on the orb.
  followup: async (s) => { await answer(s, "What time is it?", "It's 3:42 pm"); s.inject("followup", { open: true, seconds: 8 }); await sleep(1600); },
  answerText: async (s) => { await answer(s, "Is it going to rain this afternoon?", "Probably not. There's a 20% chance of a light shower around 4 pm, then it clears. 14 °C at the warmest."); },
  answerTable: async (s) => { await answer(s, "What's on my calendar tomorrow?", "Three things on Thursday, 29 October. Free after 3 pm.", CALENDAR); },
  answerCompare: async (s) => { await answer(s, "Compare laptops for travel", "The Zenbook fits travel best: lightest, longest battery, mid-priced.", LAPTOPS); },
  answerCompareLong: async (s) => { await answer(s, "Compare laptops for travel in detail", "The Zenbook fits travel best.", {
    ...LAPTOPS, size: "expanded", text: "Prices are from the makers' own stores this week.",
    rows: [...LAPTOPS.rows, ...["Ports", "Weight of charger", "Keyboard"].map((label) => ({ label, values: ["good", "fair", "good"] }))],
  }); },
  answerDiagram: async (s) => { await answer(s, "Draw how a request runs", "Most requests finish without a card; a card waits for your OK.", { ...FLOW, text: "Declining stops the run." }); },
  answerDiagramSmall: async (s) => { await answer(s, "Draw what happens when you ask", "If it needs your OK, Swift asks; otherwise it's done.", FLOW_SMALL); },
  answerDiagramWide: async (s) => { await answer(s, "Draw how a request runs, left to right", "Most requests finish without a card; a card waits for your OK.", FLOW_WIDE); },
  answerDiagramLong: async (s) => { await answer(s, "Draw how signing in works", "Swift opens Google's page; you approve there, and Swift gets a token.", SEQUENCE); },
  answerDiagramBroken: async (s) => { await answer(s, "Draw the request steps", "Three steps.", BROKEN); },
  answerMindmap: async (s) => { await answer(s, "Make me a mind map of party ideas", "Four areas: games, food, invites and music.", PARTY); },
  answerMindmapLong: async (s) => { await answer(s, "Make me a bigger mind map of party ideas", "Five areas, with decorations.", PARTY_BIG); },
  answerPdfPreview: async (s) => { await answer(s, "Preview this PDF", "The first page is a project summary.", PDF_PREVIEW); },
  answerOfficePreview: async (s) => { await answer(s, "Preview this Word document", "It opens with the rollout proposal.", OFFICE_PREVIEW); },
  answerChart: async (s) => { await answer(s, "Show quarterly active users", "Activity grew in the north and south.", CHART); },
  answerChartLong: async (s) => { await answer(s, "Show weekly active users", "The trend rises overall.", CHART_LONG); },
  answerProjects: async (s) => { await answer(s, "List my current projects", "Three active projects.", PROJECTS); },
  answerProjectsLong: async (s) => { await answer(s, "List all my current projects", "Five projects are in progress.", PROJECTS_LONG); },
  answerTyped: async (s) => { await answer(s, "convert 12 miles to km", "12 miles is **19.3 km**.", null, { typed: true }); },
  answerLong: async (s) => { await answer(s, "Give me a short history of tea", LONG); },
  // B5 (03-verify.md names): a long answer at its cap, and expanded by hand.
  cardCapped: async (s) => { await answer(s, "Give me a short history of tea", LONG); },
  cardExpanded: async (s) => { await DESIGN.answerLongOpen(s); },
  // B13: a file list as a tree.
  treeCard: async (s) => {
    await answer(s, "Where are my holiday photos?", "They're in Pictures, under 2026.", { kind: "tree", title: "Pictures", by: "worker", size: "card", entries: [
      { name: "2025", folder: true, meta: "214 items", entries: [{ name: "winter.jpg" }] },
      { name: "2026", folder: true, open: true, meta: "38 items", entries: [
        { name: "Lisbon - first evening by the river with everyone, panorama.jpg", meta: "6.1 MB" },
        { name: "beach.jpg", meta: "2.4 MB" }, { name: "trip notes.docx", meta: "18 KB" },
        { name: "Videos", folder: true, entries: [{ name: "waves.mp4" }] },
      ] },
      { name: "Screenshots", folder: true, meta: "1,204 items", entries: [{ name: "a.png" }] },
      { name: "wallpaper.png", meta: "3.0 MB" },
    ] });
  },
  // A4: an answer pinned as an edge, with the next answer in front.
  pinned: async (s) => {
    await answer(s, "What's the Wi-Fi password at the office?", "The guest network is Contoso-Guest; the password is on the card by reception.");
    [...document.querySelectorAll<HTMLButtonElement>("#card .card-foot .btn")].find((b) => b.textContent === "Pin")?.click();
    await sleep(300);
    await answer(s, "What time is it?", "It's 3:42 pm");
  },
  // A5: a Done answer with the worker's caveat.
  caveat: async (s) => {
    await answer(s, "When did tea reach England?", "Around 1650, through Portuguese and Dutch traders.", null,
      { caveat: "The two sources I read disagree by about ten years." });
  },
  answerLongOpen: async (s) => {
    await answer(s, "Give me a short history of tea", LONG);
    document.querySelector<HTMLButtonElement>("#card .card-foot .show-all")?.click();
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
  // Board 9 §5: a spoken approve held back for noise asks once more, on the same card.
  confirmAgain: async (s) => {
    await DESIGN.confirmEmail(s);
    const id = document.querySelector<HTMLElement>("#card .voice-hint[data-request]")?.dataset.request ?? "";
    s.inject("confirm.voice", { request_id: id, phase: "again", text: "Heard “approve”, but it's noisy here. Say “approve” again to go ahead, or click." });
    await sleep(150);
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
  // 5. several requests (edges behind the card, as in the app)
  concurrent: async (s) => { await concurrent(s); },
  // ADR-019 §8.4: a problem with a run nobody asked for is Failed, with Swift's origin on the left.
  failedScheduled: async (s) => { s.inject("error", { code: "service", title: "The backup couldn't finish", message: "The drive D: isn't connected. Nothing was deleted.", hint: "", severity: "error", agent: null, origin: "scheduled", origin_detail: "nightly backup" }); await sleep(150); },
  // Board 9 §4: Swift's own notices and problems (State · Notice).
  noticeReady: async () => { notice("ready"); await sleep(150); },
  noticeRunning: async () => { notice("running"); await sleep(150); },
  noticeHoldToTalk: async (s) => { s.inject("error", { code: "too_short", title: "Hold to talk", message: "Keep Ctrl+Shift+Space held while you speak, then let go.", hint: "", severity: "info", agent: null }); await sleep(150); },
  noticeNotCaught: async (s) => { s.inject("error", { code: "no_speech", title: "I didn't catch that", message: "Nothing was heard. Hold the hotkey and speak a little louder.", hint: "", severity: "info", agent: null }); await sleep(150); },
  problemStarting: async () => { notice("starting"); await sleep(150); },
  problemReconnecting: async () => { notice("reconnecting"); await sleep(150); },
  problemRestarting: async () => { notice("restarting"); await sleep(150); },
  problemStopped: async () => { notice("stopped"); await sleep(150); },
  problemCantRestart: async () => { notice("cantRestart"); await sleep(150); },
  problemHotkey: async () => { notice("hotkey"); await sleep(150); },
  // 6. the stack (inline in the harness)
  stackClosed: async (s) => { s.inject("stack", { items: STACK }); await sleep(150); },
  // Board 9 §1: the pile with no OK waiting (neutral), and with one (stackClosed, amber).
  stackPile: async (s) => { s.inject("stack", { items: STACK.slice(1) }); await sleep(150); },
  // A1: earlier today, under what waits.
  stackRecent: async (s) => {
    s.inject("stack", { items: [...STACK.slice(1), { id: "recent:a-9", kind: "recent", title: "Green tea and sleep", reason: "done", since_ms: Date.now() - 50 * 60_000, thread_id: "t9" },
      { id: "recent:a-8", kind: "recent", title: "Back up photos", reason: "failed", since_ms: Date.now() - 4 * 3_600_000, thread_id: "t8" }] });
    await sleep(100);
    document.querySelector<HTMLElement>("#stack .stack")?.click();
    await sleep(250);
  },
  stackOpen: async (s) => {
    s.inject("stack", { items: STACK });
    await sleep(100);
    document.querySelector<HTMLElement>("#stack .stack")?.click();  // one click opens it (board 9 §1)
    await sleep(250);
  },
  // 8. timers and reminders
  // Halo B14: a timer counting on the orb, alone, and with an answer card in front.
  timerOrb: async (s) => { s.inject("timers", { items: [{ id: 7, title: "Tea", due_ms: Date.now() + 252_000, set_ms: Date.now() - 48_000 }] }); await sleep(400); },
  timerTwo: async (s) => {
    s.inject("timers", { items: [{ id: 7, title: "Tea", due_ms: Date.now() + 252_000, set_ms: Date.now() - 48_000 }, { id: 8, title: "Pasta", due_ms: Date.now() + 600_000, set_ms: Date.now() }] });
    await answer(s, "What time is it?", "It's 3:42 pm");
  },
  timerDue: async (s) => {
    s.inject("state", { state: "result", run_id: "due-timer-7", agent: null });
    s.inject("result", { run_id: "due-timer-7", status: "done", summary: "Your tea timer is up.", details: null, agent: null, note: null, origin: "reminder" });
    await sleep(200);
  },
  reminderDue: async (s) => {
    s.inject("state", { state: "result", run_id: "due-reminder-3", agent: null });
    s.inject("result", { run_id: "due-reminder-3", status: "done", summary: "Reminder: call mum.", details: null, agent: null, note: null, origin: "reminder" });
    await sleep(200);
  },
  // 12. the shrunk working card, and the Deck's tightest cases (ADR-019 Step A's states)
  workingShrunk: async (s) => {
    await DESIGN.working(s);
    document.querySelector<HTMLButtonElement>('#card button[aria-label="Shrink to one line"]')?.click();
    await sleep(150);
  },
  deckFoldedRunning: async (s) => {
    const id = await answer(s, "Give me a short history of tea", LONG);
    s.inject("runs", { focus: id, waiting: 0, rows: behind().slice(0, 2).map((r) => ({ ...r, state: "working", activity: "reading", agent: AGENT })) });
    await sleep(SETTLED_MS);
    document.querySelector<HTMLButtonElement>("#card .card-foot .show-all")?.click();
    await sleep(320);
  },
  deckFoldedOk: async (s) => {
    const id = await answer(s, "Give me a short history of tea", LONG);
    s.inject("runs", { focus: id, waiting: 0, rows: behind().slice(0, 2) });
    await sleep(SETTLED_MS);
    document.querySelector<HTMLButtonElement>("#card .card-foot .show-all")?.click();
    await sleep(320);
  },
  deckConfirmTight: async (s) => {
    await DESIGN.confirmEmail(s);
    s.inject("runs", { focus: `d${n}`, waiting: 0, rows: behind() });
    await sleep(SETTLED_MS);
  },
  deckBehindSpeaking: async (s) => {
    const id = await answer(s, "What time is it?", "It's 3:42 pm");
    s.inject("runs", { focus: id, waiting: 0, rows: behind().slice(0, 1) });
    s.inject("speech", { speaking: true });
    await sleep(SETTLED_MS);
  },
  micOffWithCard: async (s) => {
    await DESIGN.answerText(s);
    s.inject("presence", { ...HERE, listening: false, paused: true });
    await sleep(150);
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

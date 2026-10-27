// Overlay renderer. The backend owns the state machine; this file draws it,
// forwards hotkeys, manages Esc registration and click-through regions. What is on screen and
// for how long is decided by the presenter (presenter.ts, ADR-013): no fade timers here.
// Failure cards, connection status, placement and dragging: ADR-009.
// Run artifacts and the "show me" detail view: ADR-010 §7. The detail view replaces the
// working card's body in place (the card never moves mid-run); Swift picks what it shows.
// Several requests (ADR-013 phase B): the others are one line each under the card (``runs``);
// a click on one, or the card in front fading while one still runs, brings it forward.
// ADR-015: those others get a small window each instead (panes.ts, pane.ts), a long answer can
// open in a reader window, and the backend hears when a confirm card is actually on screen
// (``card.seen``): its countdown runs only then. Without pane windows (the dev harness), the
// rows come back.

import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import { activityLabel, byline, handoffLabel } from "./agents";
import { el, hotkeyParts, icon, keys, withKeys } from "./dom";
import { BackendClient, type ConnectionStatus } from "./ipc";
import { Orb } from "./orb";
import * as Panes from "./panes";
import * as P from "./presenter";
import { SCENARIOS, type Activity, type Agent, type Artifact, type ErrorData, type Inbound, type ResultDetails, type Scenario, type UiState } from "./protocol";

const INFO_FADE_MS = 5000;
const ERROR_FADE_MS = 12000;
const READY_FADE_MS = 4000;
const CANCELLED_FADE_MS = 2200;
const MAX_STEPS = 5;
// Show the elapsed time once a run takes longer than this; say it's still going after STALL_MS without news.
const ELAPSED_AFTER_MS = 3000;
const STALL_MS = 20000;
// Listening this long with the level under QUIET_LEVEL: the mic probably isn't hearing anything.
const QUIET_MS = 1500;
const QUIET_LEVEL = 0.05;
const ACTIVE: ReadonlySet<UiState> = new Set(["listening", "transcribing", "working", "confirm"]);
// Failures where the log has the cause.
const LOGGED: ReadonlySet<string> = new Set(["internal", "crashed", "executor_failed", "service"]);

const stage = document.getElementById("stage")!;
const card = document.getElementById("card")!;
const rowsEl = document.getElementById("rows")!;
const transcriptEl = document.getElementById("transcript")!;
const orb = new Orb(document.getElementById("orb")!);

let state: UiState = "idle";
let steps: string[] = [];
let request = "";
// The provider working on the current run, and what it last reported doing.
let agent: Agent | null = null;
let current: { activity?: Activity; agent: Agent | null; subagent: boolean; app?: string | null } | null = null;
let runStarted = 0;
let lastStepAt = 0;
let compact = readPref("swift.compact") === "1";
let hovering = false;
let dragging = false;
// What is on screen and until when (ADR-013 §3). Changed only through present*().
let pres: P.Presenter = P.initial;
// The last messages, for the debug-build invariant report.
const recent: string[] = [];
let escapeActive = false;
let debugEnabled = false;
let pttSpec = "";
let scenarioIndex = 0;
let lastRegions = "";
let readyReported = false;
let connection: ConnectionStatus = { phase: "starting" };
let everConnected = false;
let listenStarted = 0;
let loudest = 0;
// The current run's artifacts (latest version of each), and what the detail view shows:
// undefined closed, null the steps, else an artifact id.
let artifacts = new Map<string, Artifact>();
let viewing: string | null | undefined;
let lastConfirm: Extract<Inbound, { type: "confirm.request" }>["data"] | null = null;
let fullDraft = false;
// The row last asked to come forward, so the clock asks once.
let promoted: string | null = null;
// Push-to-talk on the working card (mid-run grammar).
let runVoice: { phase: string; text: string } | null = null;
let runVoiceTimer = 0;
const DRAFT_LINES = 8;
// The confirm card the backend was last told is on screen (ADR-015 §4.2).
let seen: string | null = null;
// Pane windows (ADR-015 §3): what each open one shows. False once opening one failed: rows instead.
let paneWindows = true;
const panes = new Map<string, Panes.PaneView>();
let reader: Panes.Reader = null;
// A working card with no news for a while collapses to its line (ADR-015 §3.3); the pointer on it opens it.
let quiet = false;
let lastLookAt = 0;

const client = new BackendClient(onMessage, onStatus);

/** The push-to-talk hotkey for sentences: "Ctrl+Shift+Space". */
const pttText = (): string => (pttSpec ? hotkeyParts(pttSpec).join("+") : "the push-to-talk hotkey");
const pttKeys = (): Node => (pttSpec ? keys(pttSpec) : document.createTextNode("the push-to-talk hotkey"));

function readPref(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writePref(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Preferences are a convenience; without storage they last until restart.
  }
}

// ---- rendering ---------------------------------------------------------------

/** A new request: forget the last one's steps, artifacts and timers. */
function resetRun(keepRequest: boolean): void {
  steps = [];
  if (!keepRequest) {
    request = "";  // the transcript of a request that skipped "listening" arrived just before
    agent = null;  // the "state" message that starts a run sets it just before
  }
  current = null;
  runStarted = 0;
  artifacts = new Map();
  viewing = undefined;
  lastConfirm = null;
  fullDraft = false;
  runVoice = null;
  quiet = false;
}

/** Debug builds: a broken presenter rule is reported with the messages that led to it. */
function checkPresenter(): void {
  reportSeen();
  if (!debugEnabled) return;
  const broken = P.violations(pres);
  if (broken.length) console.warn("[overlay] presenter rule broken:", broken, "after", recent.slice(-12));
}

/** The card's drain bar and sticky state follow the presenter's deadline. */
function showDeadline(): void {
  const fadeAt = pres.card.fadeAt;
  card.classList.toggle("card--sticky", fadeAt === null && !ACTIVE.has(state));
  if (fadeAt !== null) card.style.setProperty("--fade-ms", `${Math.max(0, fadeAt - Date.now())}ms`);
  card.classList.toggle("card--paused", pres.pausedLeft !== null);
}

/** An answer, error or notice is being drawn: ``false`` means it mustn't be (busy screen, or stale). */
function presentAnswer(kind: "result" | "error" | "notice", ms: number | null, runId?: string, threadId?: string, summary?: string): boolean {
  const r = P.onAnswer(pres, { kind, runId, threadId, summary, ms }, Date.now());
  pres = r.p;
  checkPresenter();
  return r.shown;
}

/** Tell the backend which confirm card is on screen: it counts down only while one is (ADR-015 §4.2). */
function reportSeen(): void {
  const now = P.seenCard(pres);
  if (now === seen) return;
  if (seen) client.send({ type: "card.seen", data: { request_id: seen, visible: false } });
  if (now) client.send({ type: "card.seen", data: { request_id: now, visible: true } });
  seen = now;
}

// ---- other requests: a window each (ADR-015 §3), or one line each under the card -------------

const ROW_STATE: Record<string, string> = {
  queued: "Waiting to start",
  listening: "Listening",
  transcribing: "Transcribing",
  confirm: "Waiting for your answer",
  result: "Done",
  error: "Didn't finish",
  done: "Stopped",
};

function onRuns(data: Extract<Inbound, { type: "runs" }>["data"]): void {
  const rows: P.Row[] = data.rows.map((r) => ({
    runId: r.run_id, threadId: r.thread_id, title: r.title, state: r.state, activity: r.activity, app: r.app,
    startedMs: r.started_ms, summary: r.summary,
  }));
  pres = P.onRuns(pres, data.focus, rows, data.waiting);
  checkPresenter();
  if (pres.focus !== promoted) promoted = null;
  drawRows();
}

function rowLabel(r: P.Row): string {
  if (r.state === "working") return activityLabel(null, (r.activity ?? undefined) as Activity | undefined, false, r.app);
  const label = ROW_STATE[r.state] ?? "Working on it";
  return r.summary ? `${label}: ${r.summary}` : label;
}

function drawRows(): void {
  if (paneWindows) {
    drawWaiting();
    void syncPanes();
    return;
  }
  const { rows, more } = P.visibleRows(pres);
  const items: HTMLElement[] = rows.map((r) => {
    const running = !["result", "error", "done"].includes(r.state);
    const s = Math.max(0, Math.floor((Date.now() - r.startedMs) / 1000));
    return el(
      "li",
      { class: `row row--${r.state}`, "data-hit": true },
      el(
        "button",
        { class: "row-btn", title: "Bring this request to the front", onclick: () => askFocus(r.runId) },
        el("span", { class: running ? "spinner spinner--small" : "row-dot", "aria-hidden": "true" }),
        el("span", { class: "row-title" }, r.title),
        el("span", { class: "row-activity" }, rowLabel(r)),
        running ? el("span", { class: "elapsed" }, `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`) : null,
      ),
    );
  });
  if (more) items.push(el("li", { class: "row row--more" }, `+${more} more`));
  if (pres.waiting) items.unshift(el("li", { class: "row row--waiting" }, `${pres.waiting} more ${pres.waiting === 1 ? "card" : "cards"} waiting`));
  rowsEl.replaceChildren(...items);
  rowsEl.hidden = items.length === 0;
  scheduleRegions();
}

/** With pane windows, only what waits stays on the card in front: cards, and requests without a slot. */
function drawWaiting(): void {
  const items: HTMLElement[] = [];
  if (pres.waiting) items.push(el("li", { class: "row row--waiting" }, `${pres.waiting} more ${pres.waiting === 1 ? "card" : "cards"} waiting`));
  const queued = Panes.queuedRows(pres).length;
  if (queued) items.push(el("li", { class: "row row--more" }, `${queued} more ${queued === 1 ? "request" : "requests"} waiting to start`));
  rowsEl.replaceChildren(...items);
  rowsEl.hidden = items.length === 0;
  scheduleRegions();
}

/** Open, update and close pane windows to match the presenter and the reader. */
async function syncPanes(): Promise<void> {
  if (!paneWindows) return;
  const shown = new Map([...panes].map(([label, view]) => [label, JSON.stringify(view)]));
  const d = Panes.diffPanes(shown, Panes.wantedPanes(pres, reader, rowLabel));
  for (const label of d.close) {
    panes.delete(label);
    void invoke("close_pane", { label }).catch(() => {});
  }
  for (const spec of d.update) {
    panes.set(spec.label, spec.view);
    sendPane(spec.label, spec.view);
  }
  for (const spec of d.create) {
    panes.set(spec.label, spec.view);
    const { w, h } = Panes.paneSize(spec);
    try {
      await invoke("open_pane", { label: spec.label, kind: spec.kind, index: spec.index, w, h });
    } catch (err) {
      // No pane windows here (the dev harness, or an older shell): the rows under the card instead.
      console.warn("[overlay] pane windows unavailable:", err);
      paneWindows = false;
      panes.clear();
      reader = null;
      drawRows();
      return;
    }
    sendPane(spec.label, spec.view);  // if it isn't listening yet, it asks again ("ready")
  }
}

function sendPane(label: string, view: Panes.PaneView): void {
  void emitTo(label, "pane", { label, view }).catch(() => {});
}

function openReader(title: string, summary: string, details: ResultDetails | null, runId: string | null): void {
  reader = Panes.openReader(title, summary, details, runId, Date.now());
  void syncPanes();
}

void listen<{ label: string; action: string; runId?: string }>("pane-action", ({ payload }) => {
  switch (payload.action) {
    case "ready": {
      const view = panes.get(payload.label);
      if (view) sendPane(payload.label, view);
      break;
    }
    case "focus":
      if (payload.runId) askFocus(payload.runId);
      break;
    case "open":
    case "touch":
      reader = Panes.touchReader(reader, Date.now());
      void syncPanes();
      break;
    case "close":
      reader = null;
      void syncPanes();
      break;
  }
});

function askFocus(runId: string): void {
  promoted = runId;
  client.send({ type: "focus", data: { run_id: runId } });
}

/** Earlier turns of this conversation, one line each, above the card (ADR-013 §4.2). */
function threadLines(): HTMLElement | null {
  if (!pres.history.length) return null;
  return el("ul", { class: "thread", "aria-label": "Earlier in this conversation" }, ...pres.history.map((t) => el("li", {}, t.text)));
}

function setStage(next: UiState, runId: string | null = null, threadId: string | null = null): void {
  const change = P.onState(pres, next, runId, threadId);
  if (change.ignored) return;  // another request's news: its row says it
  pres = change.p;
  checkPresenter();
  state = next;
  stage.dataset.state = next;
  void syncEscape();
  if (ACTIVE.has(next)) card.classList.remove("card--sticky");
  // A new request, however it started (follow-up, correction, "hey Swift, X" in one breath).
  if (change.newRun && next !== "listening") resetRun(true);

  if (next === "listening") orb.listen();
  else if (next === "transcribing") orb.settle();
  else orb.stop();

  if (next === "listening") {
    resetRun(false);
    listenStarted = performance.now();
    loudest = 0;
    delete transcriptEl.dataset.quiet;
    transcriptEl.textContent = "";
    card.replaceChildren();
    card.className = "card";
  }
  if (next === "transcribing") {
    transcriptEl.dataset.pending = "true";
    delete transcriptEl.dataset.quiet;
  }
  if (next === "working") {
    if (!runStarted) runStarted = lastStepAt = Date.now();
    renderWorking();
  }
  if (next === "idle") hideCard();
}

/** A card the backend didn't ask for (connection, hotkeys, startup): at rest, like a result. */
function rest(next: "result" | "error"): void {
  state = next;
  stage.dataset.state = next;
  void syncEscape();
}

function showCard(node: HTMLElement, variant: string, role: "status" | "alert" = "status"): void {
  card.className = `card card--${variant} card--in${hovering ? " card--hover" : ""}`;
  card.setAttribute("role", role);
  card.replaceChildren(node);
  scheduleRegions();
}

function hideCard(): void {
  card.classList.remove("card--in");
  card.classList.add("card--out");
  scheduleRegions();
  window.setTimeout(() => {
    if (card.classList.contains("card--out")) {
      card.replaceChildren();
      card.className = "card";
      stage.dataset.state = state === "result" || state === "error" ? "idle" : state;
      scheduleRegions();
    }
  }, 260);
}

function dismiss(): void {
  const r = P.onDismiss(pres);
  pres = r.p;
  if (r.hide) setStage("idle");
}

/** Card header: drag handle (data-drag) for moving the overlay, with an optional close button. */
function head(glyph: Node | null, title: Node | string, extra: (Node | null)[] = [], closable = true): HTMLElement {
  return el(
    "header",
    { class: "card-head", "data-hit": true, "data-drag": true, title: "Drag to move Swift" },
    glyph,
    typeof title === "string" ? el("span", { class: "card-title" }, title) : title,
    el("span", { class: "head-extra" }, ...extra),
    closable ? el("button", { class: "icon-btn", "aria-label": "Dismiss", title: "Dismiss", onclick: () => dismiss() }, icon("x")) : null,
  );
}

function elapsedText(): string {
  const s = Math.floor((Date.now() - runStarted) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function renderWorking(): void {
  const busyAt = Date.now();
  // A new step re-renders the card: keep the reader's place in an open draft.
  const scrolled = card.querySelector<HTMLElement>(".draft-body")?.scrollTop ?? 0;
  const list = el("ol", { class: "steps" });
  steps.forEach((text, i) => {
    const latest = i === steps.length - 1;
    list.append(el("li", { class: latest ? "step step--latest" : "step" }, el("span", { class: "step-dot" }), el("span", { class: "step-text" }, text)));
  });
  const title = current ? activityLabel(current.agent, current.activity, current.subagent, current.app) : handoffLabel(agent);
  const toggle = el(
    "button",
    {
      class: "icon-btn",
      "aria-label": compact ? "Show steps" : "Hide steps",
      title: compact ? "Show steps" : "Hide steps",
      "aria-expanded": compact ? "false" : "true",
      onclick: () => {
        compact = !compact;
        writePref("swift.compact", compact ? "1" : "0");
        renderWorking();
      },
    },
    icon(compact ? "expand" : "collapse"),
  );
  const elapsed = el("span", { class: "elapsed", "aria-hidden": "true" }, runStarted && busyAt - runStarted > ELAPSED_AFTER_MS ? elapsedText() : "");
  // "Show me" on the steps (viewing null) opens them even in compact mode.
  const shown = viewing ? artifacts.get(viewing) : undefined;
  const small = (compact || quiet) && viewing === undefined;
  const stalled = isStalled(busyAt);
  const showButton = artifacts.size && !shown
    ? el("button", { class: "btn btn--ghost btn--small", "data-hit": true, title: "Show what Swift is working on", onclick: () => askView("show") }, "Show")
    : null;
  const backButton = shown
    ? el("button", { class: "btn btn--ghost btn--small", "data-hit": true, onclick: () => askView("hide") }, "Back to steps")
    : null;
  showCard(
    el(
      "div",
      {},
      head(el("span", { class: "spinner", "aria-hidden": "true" }), el("span", { class: "card-title card-title--live" }, title), [elapsed, toggle], false),
      small ? null : threadLines(),
      small || shown ? null : request ? el("p", { class: "request" }, request) : null,
      shown ? artifactView(shown) : small ? null : steps.length ? list : null,
      stalled ? el("p", { class: "note note--soft" }, "Still working. Bigger requests can take a few minutes.") : null,
      runVoice ? runVoiceLine(runVoice) : null,
      el(
        "footer",
        { class: "card-foot" },
        el("span", { class: "hint" }, el("kbd", {}, "Esc"), " to stop"),
        el("span", { class: "actions actions--inline" }, backButton ?? showButton, el("button", { class: "btn btn--ghost btn--small", "data-hit": true, onclick: () => cancelRun() }, "Stop")),
      ),
    ),
    small ? "working card--compact" : "working",
  );
  const body = card.querySelector<HTMLElement>(".draft-body");
  if (body && scrolled) body.scrollTop = scrolled;
}

/** "Still working" shows on the steps only, never over an open artifact or a collapsed card. */
function isStalled(now: number): boolean {
  const open = viewing ? artifacts.has(viewing) : false;
  return !(compact && viewing === undefined) && !open && steps.length > 0 && now - lastStepAt > STALL_MS;
}

function askView(action: "show" | "hide"): void {
  client.send({ type: "view", data: { action } });
}

function runVoiceLine(v: { phase: string; text: string }): HTMLElement {
  return el(
    "p",
    { class: "voice-hint", "data-phase": v.phase, "aria-live": "polite" },
    v.phase === "listening" ? icon("mic") : null,
    v.phase === "listening" ? "Listening…" : v.phase === "transcribing" ? "Transcribing…" : v.text,
  );
}

// ---- artifacts (ADR-010) ------------------------------------------------------------

const SEND_TEXT: Record<string, string> = {
  waiting_approval: "Waiting for your approval",
  sending: "Sending…",
  sent: "Sent",
  failed: "Not sent",
  rejected: "Not sent: you didn't approve it",
  filled_in: "Filled in for you: check it and press Send",
};
// The same states, for a calendar event.
const EVENT_TEXT: Record<string, string> = {
  waiting_approval: "Waiting for your approval",
  sending: "Adding…",
  sent: "Added to your calendar",
  failed: "Not added",
  rejected: "Not added: you didn't approve it",
};
// A change (``before`` set) or a removal (``removing``) says so instead.
const CHANGE_TEXT: Record<string, string> = { ...EVENT_TEXT, sending: "Changing…", sent: "Changed", failed: "Not changed", rejected: "Not changed: you didn't approve it" };
const REMOVE_TEXT: Record<string, string> = { ...EVENT_TEXT, sending: "Removing…", sent: "Removed from your calendar", failed: "Not removed", rejected: "Not removed: you didn't approve it" };

/** One artifact, readable at a glance. Bodies scroll inside the card, which stays put. */
function artifactView(a: Artifact, clipLines = 0, titled = true): HTMLElement {
  const label = a.kind === "email_draft" ? `Draft${a.version > 1 ? ` · v${a.version}` : ""}` : a.title;
  let body: HTMLElement;
  switch (a.kind) {
    case "email_draft": {
      const to = a.data.to.map((p) => (p.name ? `${p.name} <${p.email}>` : p.email)).join(", ");
      const lines = a.data.body.split("\n");
      const clipped = clipLines > 0 && lines.length > clipLines;
      body = el(
        "div",
        {},
        el("dl", { class: "kv" }, el("dt", {}, "To"), el("dd", {}, to), el("dt", {}, "Subject"), el("dd", {}, a.data.subject)),
        el("div", { class: "draft-body", tabindex: "0" }, clipped ? lines.slice(0, clipLines).join("\n") + "\n…" : a.data.body),
      );
      break;
    }
    case "recipient": {
      const { candidates, chosen } = a.data;
      body = candidates.length
        ? el("ul", { class: "result-list" }, ...candidates.map((p, i) => el("li", { class: i === chosen ? "chosen" : "" }, `${p.name} <${p.email}>`)))
        : el("p", { class: "muted" }, `No contact matches “${a.data.query}”.`);
      break;
    }
    case "send_status": {
      // What was (or wasn't) sent, under its status.
      const draft = a.data.draft_id ? artifacts.get(a.data.draft_id) : undefined;
      body = el(
        "div",
        {},
        el("p", { class: `summary send-${a.data.state}` }, SEND_TEXT[a.data.state] ?? a.data.state),
        a.data.reason ? el("p", { class: "muted" }, a.data.reason) : null,
        draft?.kind === "email_draft"
          ? el("dl", { class: "kv kv--after" }, el("dt", {}, "To"), el("dd", {}, draft.data.to.map((p) => p.name || p.email).join(", ")), el("dt", {}, "Subject"), el("dd", {}, draft.data.subject))
          : null,
      );
      break;
    }
    case "calendar_event": {
      const e = a.data;
      body = el(
        "div",
        {},
        e.state ? el("p", { class: `summary send-${e.state === "sent" ? "sent" : e.state}` }, (e.removing ? REMOVE_TEXT : e.before ? CHANGE_TEXT : EVENT_TEXT)[e.state] ?? e.state) : null,
        e.reason ? el("p", { class: "muted" }, e.reason) : null,
        el("dl", { class: "kv" }, el("dt", {}, "What"), el("dd", {}, e.title), el("dt", {}, "When"), el("dd", {}, e.when),
          ...(e.location ? [el("dt", {}, "Where"), el("dd", {}, e.location)] : []),
          ...(e.attendees ? [el("dt", {}, "Who"), el("dd", {}, e.attendees)] : []),
          ...(e.meet ? [el("dt", {}, "Meet"), el("dd", {}, "with a Google Meet link")] : [])),
        Array.isArray(e.changes) && e.changes.length
          ? el("ul", { class: "result-list" }, ...e.changes.map((c) => el("li", {}, c)))
          : null,
      );
      break;
    }
    default:
      body = renderDetails(a.data) ?? el("p", { class: "muted" }, "");
  }
  return el("section", { class: "artifact", role: "region", "aria-label": label, "data-hit": true }, titled ? el("h3", { class: "artifact-title" }, label) : null, body);
}

/** After the run: "show me" (or Show) on a result opens the artifact as its own card. */
function renderArtifactCard(a: Artifact): void {
  if (!presentAnswer("result", readingMs(a.kind === "email_draft" ? a.data.body : a.title), a.run_id, pres.threadId ?? undefined)) return;
  rest("result");
  showCard(
    el("div", { "data-hit": true, class: "hit-area", onclick: dismissUnlessControl }, head(icon("info"), a.title), artifactView(a, 0, false)),
    "result card--neutral",
  );
  showDeadline();
}

function onArtifact(a: Artifact): void {
  const known = artifacts.get(a.id);
  if (known && known.version >= a.version) return; // late or repeated
  const first = artifacts.size === 0;
  artifacts.set(a.id, a);
  if (state === "working" && (first || viewing === a.id)) renderWorking();
}

function onView(v: Extract<Inbound, { type: "view" }>["data"]): void {
  if (state === "confirm" && lastConfirm) {
    // On the send card the draft is already there: "show me" opens all of it.
    fullDraft = v.open;
    renderConfirm(lastConfirm);
    return;
  }
  if (state === "working") {
    viewing = v.open ? v.artifact_id : undefined;
    renderWorking();
    return;
  }
  const a = v.artifact_id ? artifacts.get(v.artifact_id) : undefined;
  if (v.open && a && (state === "result" || state === "error" || state === "idle")) renderArtifactCard(a);
  else if (!v.open && card.querySelector(".artifact")) setStage("idle");
}

// ---- presence: the tray tooltip says whether Swift is listening, and why not (ADR-014 §8) ----

function onPresence(p: Extract<Inbound, { type: "presence" }>["data"]): void {
  const hold = `Hold ${pttText()} to talk.`;
  let text = `Swift: ready. ${hold}`;
  if (p.wake && p.listening) text = `Swift: listening for “hey Swift”. Or ${hold.toLowerCase()}`;
  else if (p.wake && p.reason === "locked") text = "Swift: paused while the screen is locked.";
  else if (p.wake && p.reason === "asleep") text = "Swift: paused (the PC was asleep).";
  void invoke("set_status", { text }).catch(() => {});
}

// ---- follow-up window: reply without the wake phrase, just after an answer ---------------

// The answer asked something: Swift waits longer, and the line says it's waiting for the answer.
let followupQuestion = false;

function onFollowup(data: Extract<Inbound, { type: "followup" }>["data"]): void {
  // The presenter keeps the answer up at least as long as Swift listens for a reply.
  followupQuestion = data.open && !!data.question;
  pres = P.onFollowup(pres, data.open, data.seconds, Date.now());
  showDeadline();
  drawFollowup(pres.followupUntil ? Math.ceil((pres.followupUntil - Date.now()) / 1000) : 0);
}

function drawFollowup(left: number): void {
  let line = card.querySelector<HTMLElement>(".followup");
  if (left <= 0 || (state !== "result" && state !== "error")) {
    line?.remove();
    return;
  }
  if (!line) {
    line = el("p", { class: "voice-hint followup", "data-phase": "listening", "aria-live": "off" });
    (card.firstElementChild ?? card).append(line);
    scheduleRegions();
  }
  line.replaceChildren(icon("mic"), `${followupQuestion ? "Listening for your answer" : "Listening for a reply"}… ${left} s`);
}

function onRunVoice(v: Extract<Inbound, { type: "run.voice" }>["data"]): void {
  window.clearTimeout(runVoiceTimer);
  runVoice = v.phase === "idle" ? null : v;
  // A hint stays long enough to read, then the card goes back to normal.
  if (v.phase === "hint") runVoiceTimer = window.setTimeout(() => { runVoice = null; if (state === "working") renderWorking(); }, 4000);
  if (state === "working") renderWorking();
}

function cancelRun(): void {
  client.send({ type: "cancel", data: {} });
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
}

function renderConfirm(data: Extract<Inbound, { type: "confirm.request" }>["data"]): void {
  const reply = (decision: "approve" | "reject") => () => {
    client.send({ type: "confirm.reply", data: { request_id: data.request_id, decision } });
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  };
  // A re-render (show me / hide on the card) keeps the deadline it already had.
  const again = lastConfirm?.request_id === data.request_id;
  if (!again) fullDraft = false;
  lastConfirm = data;
  // The countdown and "since" are the presenter's: a card put aside and back gets a fresh one.
  const confirmDeadline = pres.pendingConfirm === data.request_id ? pres.confirmDeadline : 0;
  const since = pres.pendingConfirm === data.request_id ? P.waitingSince(pres) : null;
  // Swift's own card (send_email) shows the draft itself (ADR-010 §4).
  const shown = data.artifact_id ? artifacts.get(data.artifact_id) : undefined;
  const longDraft = shown?.kind === "email_draft" && shown.data.body.split("\n").length > DRAFT_LINES;
  showCard(
    el(
      "div",
      { "data-hit": true },
      head(icon("shield"), "Approval needed", [data.tool && !shown ? el("span", { class: "chip" }, data.tool) : null], false),
      since !== null
        ? el("p", { class: "voice-hint waiting", "data-phase": "hint" }, icon("info"), `1 card waiting, since ${clock(since)}`)
        : null,
      threadLines(),
      data.agent ? el("p", { class: "asker" }, `${data.agent.name} wants to:`) : null,
      el("p", { class: "confirm-title" }, data.title),
      shown ? artifactView(shown, fullDraft ? 0 : DRAFT_LINES) : data.detail ? el("p", { class: "muted detail-text" }, data.detail) : null,
      longDraft
        ? el("button", { class: "link", "aria-expanded": String(fullDraft), onclick: () => askView(fullDraft ? "hide" : "show") }, fullDraft ? "Show less" : "Show full draft")
        : null,
      el("p", { class: "voice-hint", "data-request": data.request_id }, ...voiceHint(data)),
      el("p", { class: "countdown", "aria-live": "off" }),
      el(
        "div",
        { class: "actions" },
        el("button", { class: "btn btn--ghost", onclick: reply("reject") }, "Reject"),
        el("button", { class: "btn btn--primary", onclick: reply("approve") }, "Approve"),
      ),
    ),
    "confirm",
  );
  if (confirmDeadline) {
    card.style.setProperty("--fade-ms", `${Math.max(0, confirmDeadline - Date.now())}ms`);
    card.classList.add("card--timed");
  }
  // Redrawn while the owner is away (a new draft version): it stays put aside.
  if (pres.held === data.request_id) card.classList.add("card--held");
  tickConfirm();
}

const clock = (ms: number): string => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** The owner left: put the card aside (hidden, no countdown). Back: show it again, saying it waited. */
function onConfirmHold(data: Extract<Inbound, { type: "confirm.hold" }>["data"]): void {
  pres = P.onConfirmHold(pres, data.request_id, data.held, data.timeout_s, Date.now());
  checkPresenter();
  // Back: the backend has just drawn the card again (ADR-015 §4.1), so a card this overlay had
  // forgotten while it was hidden is already on screen (owner check 18, 2026-10-27).
  if (!lastConfirm || lastConfirm.request_id !== data.request_id || pres.pendingConfirm !== data.request_id) return;
  if (data.held) {
    card.classList.add("card--held");
  } else {
    if (state !== "confirm") setStage("confirm");
    renderConfirm(lastConfirm);  // the same card, with a fresh countdown and the "waiting" line
    // Locking the screen can leave the overlay hidden or behind other windows, and no hotkey
    // brought it forward this time (owner check 14, 2026-10-27).
    void invoke("reveal").catch(() => {});
  }
  scheduleRegions();
}

/** After an answer: one line naming a conversation left unfinished. */
function onResumeOffer(data: Extract<Inbound, { type: "resume.offer" }>["data"]): void {
  if (state !== "result" && state !== "error") return;
  card.querySelector(".resume")?.remove();
  const line = el("p", { class: "voice-hint resume", "data-phase": "hint" }, icon("info"), `Unfinished: ${data.title}. Say “continue”, or “not now”.`);
  (card.firstElementChild ?? card).append(line);
  scheduleRegions();
}

/** The voice line on a confirm card: any card takes a change ("no, make it Friday"), whichever agent asked. */
function voiceHint(_data: unknown): (Node | string)[] {
  return ["Or hold ", pttKeys(), " and say “approve”, “reject”, or what to change."];
}

function tickConfirm(): void {
  const node = card.querySelector<HTMLElement>(".countdown");
  const confirmDeadline = pres.confirmDeadline;
  if (!node || state !== "confirm" || !confirmDeadline) return;
  const left = Math.max(0, Math.ceil((confirmDeadline - Date.now()) / 1000));
  // Only the last half minute: earlier, a ticking clock is just pressure.
  node.textContent = left <= 30 ? `No answer in ${left} s stops the request.` : "";
}

// The owner is answering the confirm card by voice: show it on the card, not as the
// listening orb (which would cover the card and clear it).
function renderConfirmVoice(data: Extract<Inbound, { type: "confirm.voice" }>["data"]): void {
  const hint = card.querySelector<HTMLElement>(".voice-hint");
  if (state !== "confirm" || !hint || hint.dataset.request !== data.request_id) return;
  hint.dataset.phase = data.phase;
  if (data.phase === "listening") hint.replaceChildren(icon("mic"), "Listening…");
  else if (data.phase === "transcribing") hint.textContent = "Transcribing…";
  else if (data.phase === "hint") hint.textContent = data.text;
  // A voice approval Swift held back (noise, or not sure what it heard): it needs one more.
  else if (data.phase === "again") hint.replaceChildren(icon("alert"), data.text);
  else hint.replaceChildren(...voiceHint(lastConfirm));
}

function detailsText(details: ResultDetails | null | undefined): string {
  if (!details) return "";
  switch (details.kind) {
    case "text":
      return details.text;
    case "list":
      return details.items.map((i) => `- ${i}`).join("\n");
    case "table":
      return [details.columns, ...details.rows].map((r) => r.join("\t")).join("\n");
  }
}

function renderDetails(details: ResultDetails | null | undefined): HTMLElement | null {
  if (!details) return null;
  switch (details.kind) {
    case "text":
      return el("p", { class: "muted" }, details.text);
    case "list": {
      const more = details.items.length - 6;
      return el(
        "div",
        {},
        el("ul", { class: "result-list" }, ...details.items.slice(0, 6).map((item) => el("li", {}, item))),
        more > 0 ? el("p", { class: "more" }, `and ${more} more (Copy includes them)`) : null,
      );
    }
    case "table": {
      const more = details.rows.length - 6;
      return el(
        "div",
        { class: "table-wrap" },
        el(
          "table",
          { class: "result-table" },
          el("thead", {}, el("tr", {}, ...details.columns.map((c) => el("th", { scope: "col" }, c)))),
          el("tbody", {}, ...details.rows.slice(0, 6).map((row) => el("tr", {}, ...row.map((c) => el("td", {}, c))))),
        ),
        more > 0 ? el("p", { class: "more" }, `and ${more} more rows (Read all or Copy shows them)`) : null,
      );
    }
  }
}

/** Long answers stay up longer: about 4 s to notice plus reading time, within 6 to 20 s. */
function readingMs(text: string): number {
  return Math.min(20000, Math.max(6000, 4000 + text.length * 45));
}

function copyButton(text: string): HTMLElement {
  const button = el("button", { class: "btn btn--ghost btn--small", title: "Copy the answer" }, icon("copy"), "Copy");
  button.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    try {
      await invoke("copy_text", { text });
      button.replaceChildren(icon("check"), "Copied");
    } catch {
      button.replaceChildren("Couldn't copy");
    }
    window.setTimeout(() => button.replaceChildren(icon("copy"), "Copy"), 1600);
  });
  return button;
}

function renderResult(data: Extract<Inbound, { type: "result" }>["data"]): void {
  if (data.status === "cancelled") {
    // Esc or "stop": the owner knows what happened, so just acknowledge it.
    if (!presentAnswer("result", CANCELLED_FADE_MS, data.run_id, data.thread_id)) return;
    showCard(el("div", { "data-hit": true, class: "hit-area", onclick: dismiss }, head(icon("stop"), "Cancelled")), "result card--neutral card--compact");
    showDeadline();
    return;
  }
  const variant = data.status === "done" ? "done" : "neutral";
  const glyph = data.status === "done" ? "check" : "x";
  const label = { done: "Done", rejected: "Not approved", error: "Failed" }[data.status];
  // What the run finished showing (the calendar's table, ADR-015 §6) is part of the answer.
  const finished = finishedArtifacts();
  const extra = [detailsText(data.details), ...finished.map((a) => `${a.title}\n${detailsText(a.data)}`)].filter(Boolean).join("\n\n");
  const copyable = [data.summary, extra].filter(Boolean).join("\n\n");
  const readable = finished.length ? finished[finished.length - 1] : null;
  const fuller = data.details ?? readable?.data ?? null;
  const readAll = paneWindows && (Panes.needsReader(data.summary, fuller) || finished.length > 1)
    ? el("button", { class: "btn btn--ghost btn--small", title: "Open the whole answer in a larger window", onclick: () =>
        openReader(readable?.title ?? clipLine(request || label), data.summary, fuller, data.run_id) }, "Read all")
    : null;
  const line = `${data.status === "rejected" ? "Not approved: " : ""}${clipLine(data.summary)}`;
  if (!presentAnswer("result", readingMs(copyable), data.run_id, data.thread_id, line)) return;
  showCard(
    el(
      "div",
      { "data-hit": true, class: "hit-area", onclick: dismissUnlessControl },
      head(icon(glyph), label),
      threadLines(),
      data.note ? el("p", { class: "note" }, data.note) : null,
      el("p", { class: "summary" }, data.summary),
      renderDetails(data.details),
      ...finished.map((a) => el("section", { class: "artifact", "aria-label": a.title }, el("h3", { class: "artifact-title" }, a.title), renderDetails(a.data))),
      el(
        "footer",
        { class: "card-foot" },
        el("span", { class: "byline" }, byline(data.agent)),
        el(
          "span",
          { class: "actions actions--inline" },
          readAll,
          // What the run produced (the sent email) stays one click (or "show me") away.
          artifacts.size > finished.length ? el("button", { class: "btn btn--ghost btn--small", onclick: () => askView("show") }, "Show") : null,
          data.status === "done" ? copyButton(copyable) : null,
        ),
      ),
    ),
    `result card--${variant}`,
  );
  showDeadline();
}

/** Tables, lists and text the run finished showing (the calendar's "Your calendar: …"). */
type Finished = Extract<Artifact, { kind: "text" | "list" | "table" }>;
function finishedArtifacts(): Finished[] {
  return [...artifacts.values()].filter((a): a is Finished => (a.kind === "table" || a.kind === "list" || a.kind === "text") && a.phase === "done");
}

/** One line of an answer, for the thread's history. */
function clipLine(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length <= 90 ? flat : `${flat.slice(0, 89).trimEnd()}…`;
}

/** Clicking a card dismisses it, except on its buttons and expandable details. */
function dismissUnlessControl(ev: Event): void {
  if ((ev.target as HTMLElement).closest("button, .detail, details")) return;
  dismiss();
}

// Shown when Swift is launched again while already running (single-instance plugin).
function renderAlreadyRunning(): void {
  if (!presentAnswer("notice", READY_FADE_MS + 1500)) return; // never over a request
  rest("result");
  showCard(
    el(
      "div",
      { "data-hit": true, class: "hit-area", onclick: dismiss },
      head(icon("check"), "Swift is already running"),
      el("p", { class: "summary" }, "Hold ", pttKeys(), " and speak."),
      el("p", { class: "muted" }, "Only one copy of Swift runs at a time. Its icon is in the system tray."),
    ),
    "result card--done",
  );
  showDeadline();
}

function renderReady(): void {
  if (card.classList.contains("card--in") || !presentAnswer("notice", READY_FADE_MS)) return;
  rest("result");
  showCard(
    el("div", { "data-hit": true, class: "hit-area", onclick: dismiss }, head(icon("check"), "Swift is ready"), el("p", { class: "summary" }, "Hold ", pttKeys(), " and speak.")),
    "result card--done card--compact-body",
  );
  showDeadline();
}

type Problem = {
  title: string;
  message: string;
  hint?: string;
  detail?: string | null;
  severity?: "error" | "info";
  retry?: boolean;
  logs?: boolean;
  agent?: Agent | null;
  // Stays until dismissed: Swift can't work until it's fixed.
  sticky?: boolean;
  glyph?: string;
  runId?: string;
  threadId?: string;
};

function renderProblem(p: Problem): void {
  const info = p.severity === "info";
  if (!presentAnswer("error", p.sticky ? null : info ? INFO_FADE_MS : ERROR_FADE_MS, p.runId, p.threadId, clipLine(p.title))) return;
  rest("error");
  let open = false;
  const detail = p.detail ? el("pre", { class: "detail", hidden: true }, p.detail) : null;
  const toggle = detail
    ? el("button", { class: "link", "aria-expanded": "false", onclick: () => {
        open = !open;
        detail.hidden = !open;
        toggle!.setAttribute("aria-expanded", String(open));
        toggle!.textContent = open ? "Hide details" : "Show details";
        scheduleRegions();
      } }, "Show details")
    : null;
  const actions: HTMLElement[] = [];
  if (p.logs) actions.push(el("button", { class: "btn btn--ghost btn--small", onclick: () => void invoke("open_logs") }, "Open logs"));
  if (p.retry) {
    actions.push(
      el("button", { class: "btn btn--primary btn--small", onclick: (ev: Event) => {
        (ev.currentTarget as HTMLButtonElement).disabled = true;
        if (!client.send({ type: "retry", data: {} })) renderConnection(true);
      } }, "Try again"),
    );
  }
  showCard(
    el(
      "div",
      { "data-hit": true, class: "hit-area", onclick: dismissUnlessControl },
      head(icon(p.glyph ?? (info ? "info" : "alert")), el("span", { class: "card-title card-title--sentence" }, p.title)),
      el("p", { class: "summary" }, withKeys(p.message, pttSpec)),
      p.hint ? el("p", { class: "muted" }, withKeys(p.hint, pttSpec)) : null,
      detail,
      toggle || actions.length || p.agent
        ? el(
            "footer",
            { class: "card-foot" },
            toggle ?? (p.agent ? el("span", { class: "byline" }, byline(p.agent)) : el("span")),
            actions.length ? el("span", { class: "actions actions--inline" }, ...actions) : null,
          )
        : null,
    ),
    info ? "error card--info" : "error",
    info ? "status" : "alert",
  );
  showDeadline();
}

function renderError(data: ErrorData): void {
  renderProblem({
    title: data.title || (data.agent ? `${data.agent.name} ran into a problem` : "Something went wrong"),
    message: data.message,
    hint: data.hint,
    detail: data.detail,
    severity: data.severity ?? "error",
    retry: data.retry,
    logs: LOGGED.has(data.code),
    agent: data.agent ?? null,
    threadId: data.thread_id,
  });
}

/** What the owner sees about the backend connection when it matters (PTT, startup failure). */
function renderConnection(asked: boolean): void {
  const status = connection;
  if (status.phase === "connected") return;
  if (status.phase === "starting") {
    if (!asked) return;
    renderProblem({ title: "Swift is still starting", message: "It'll be ready in a moment. Try again in a few seconds.", severity: "info", glyph: "info" });
    return;
  }
  if (status.phase === "lost") {
    rest("error");
    showCard(
      el("div", { "data-hit": true }, head(el("span", { class: "spinner", "aria-hidden": "true" }), el("span", { class: "card-title card-title--sentence" }, "Reconnecting to Swift…"), [], true), el("p", { class: "muted" }, "Your next request will work once it's back.")),
      "error card--info card--compact-body",
    );
    return;
  }
  renderProblem({ ...describeBackendProblem(status.problem), sticky: true, logs: true });
}

function describeBackendProblem(problem: string): Problem {
  if (problem.startsWith("config ")) {
    return {
      title: "There's a problem in config.yaml",
      message: "Swift couldn't read its settings, so it can't start.",
      hint: "Fix the setting shown in the details, then start Swift again.",
      detail: problem.slice("config ".length),
    };
  }
  if (problem.includes("could not start the backend")) {
    return {
      title: "Swift couldn't start",
      message: "Its speech and agent engine didn't launch.",
      hint: "Check the Python setup in the README (`uv sync`), then start Swift again.",
      detail: problem,
    };
  }
  if (problem.includes("session token")) {
    return {
      title: "Swift lost its connection",
      message: "The overlay and Swift's engine stopped trusting each other.",
      hint: "Quit Swift from the tray icon and start it again.",
      detail: problem,
    };
  }
  return {
    title: "Swift's engine stopped",
    message: "The part of Swift that listens and runs requests quit unexpectedly.",
    hint: "Quit Swift from the tray icon and start it again. The logs say what happened.",
    detail: problem,
  };
}

// ---- hover and drag hold an answer (the presenter keeps the time) -------------------

function setHold(): void {
  pres = P.onHold(pres, hovering || dragging, Date.now());
  showDeadline();
}

function setHover(inside: boolean): void {
  hovering = inside;
  card.classList.toggle("card--hover", inside);
  if (inside) lastLookAt = Date.now();
  if (inside && quiet) {
    quiet = false;
    if (state === "working") renderWorking();
  }
  setHold();
}

// ---- the one clock: answers fade and the reply window counts down only here ---------

window.setInterval(() => {
  const r = P.tick(pres, Date.now());
  pres = r.p;
  if (r.hide) setStage("idle");
  drawFollowup(r.followupLeft);
  // The card in front is gone but another request still runs: bring it forward.
  const next = P.promotion(pres);
  if (next && next !== promoted) askFocus(next);
}, 250);

// ---- click-through regions ---------------------------------------------------

// Timers, not requestAnimationFrame: rAF can be throttled for a background
// webview, and a stale region would leave an invisible click-blocking area.
let regionTimers: number[] = [];

function sendRegions(): void {
  const visible = (card.classList.contains("card--in") && !card.classList.contains("card--held")) || !rowsEl.hidden;
  // Outermost hit areas only: a nested one adds nothing.
  const rects = visible
    ? Array.from(document.querySelectorAll<HTMLElement>("[data-hit]"))
        .filter((node) => !node.parentElement?.closest("[data-hit]"))
        .map((node) => {
          const r = node.getBoundingClientRect();
          return { x: r.left, y: r.top, w: r.width, h: r.height };
        })
    : [];
  const key = JSON.stringify(rects);
  if (key === lastRegions) return;
  lastRegions = key;
  void invoke("set_hit_regions", { rects });
}

function scheduleRegions(): void {
  regionTimers.forEach((t) => window.clearTimeout(t));
  // Now, and again once the card's entry transform (240 ms) has settled.
  regionTimers = [window.setTimeout(sendRegions, 0), window.setTimeout(sendRegions, 300)];
  if (!card.classList.contains("card--in")) sendRegions();
}
new ResizeObserver(scheduleRegions).observe(card);

// ---- moving the overlay -----------------------------------------------------------

// Pressing a card's header hands the drag to Rust, which follows the cursor
// and snaps to the nearest anchor on release (a press without moving is a click).
card.addEventListener("pointerdown", (ev) => {
  const target = ev.target as HTMLElement;
  if (ev.button !== 0 || target.closest("button") || !target.closest("[data-drag]")) return;
  void invoke("begin_drag");
});

function setAnchor(anchor: string): void {
  stage.dataset.anchor = anchor;
  scheduleRegions();
}

// ---- once a second: elapsed time, stall note, confirm countdown -----------------

window.setInterval(() => {
  if (state === "working") {
    const node = card.querySelector<HTMLElement>(".elapsed");
    if (node && Date.now() - runStarted > ELAPSED_AFTER_MS) node.textContent = elapsedText();
    if (isStalled(Date.now()) !== !!card.querySelector(".note--soft")) renderWorking();
    // No news and nobody looking: collapse to the one line (ADR-015 §3.3).
    if (!quiet && Panes.workingQuiet(Math.max(lastStepAt, runStarted, lastLookAt), Date.now(), hovering)) {
      quiet = true;
      renderWorking();
    }
  } else if (state === "confirm") tickConfirm();
  if (pres.rows.length && !paneWindows) drawRows();  // their elapsed time (pane windows keep their own)
  const shrunk = Panes.readerTick(reader, Date.now(), false);
  if (shrunk !== reader) {
    reader = shrunk;
    void syncPanes();
  }
}, 1000);

// ---- Esc: only grabbed while Swift is active ------------------------------------

async function syncEscape(): Promise<void> {
  const want = ACTIVE.has(state);
  if (want === escapeActive) return;
  escapeActive = want;
  try {
    await invoke("set_escape", { active: want });
  } catch (err) {
    console.warn("Esc hotkey:", err);
  }
}

// ---- backend messages ----------------------------------------------------------

function onMessage(msg: Inbound): void {
  if (msg.type !== "level") recent.push(`${msg.type}${"state" in msg.data ? `:${msg.data.state}` : ""}`), recent.splice(0, recent.length - 30);
  switch (msg.type) {
    case "hello.ok":
      debugEnabled = msg.data.debug;
      if (msg.data.hotkeys.push_to_talk) pttSpec = msg.data.hotkeys.push_to_talk;
      void registerHotkeys(msg.data.hotkeys);
      void invoke("set_status", { text: `Swift: ready. Hold ${pttText()} to talk.` }).catch(() => {});
      break;
    case "state":
      if (msg.data.agent !== undefined) agent = msg.data.agent;
      setStage(msg.data.state, msg.data.run_id ?? null, msg.data.thread_id ?? null);
      break;
    case "level":
      orb.setLevel(msg.data.rms);
      noteLevel(msg.data.rms);
      break;
    case "transcript":
      transcriptEl.textContent = msg.data.text;
      if (msg.data.text) delete transcriptEl.dataset.quiet;
      if (msg.data.final) {
        delete transcriptEl.dataset.pending;
        request = msg.data.text;
      }
      break;
    case "step":
      steps = [...steps, msg.data.text].slice(-MAX_STEPS);
      lastStepAt = Date.now();
      quiet = false;
      current = { activity: msg.data.activity, agent: msg.data.agent ?? agent, subagent: msg.data.subagent ?? false, app: msg.data.app };
      if (state === "working") renderWorking();
      break;
    case "confirm.request":
      pres = P.onConfirm(pres, msg.data.request_id, msg.data.run_id, msg.data.timeout_s ?? 0, Date.now());
      checkPresenter();
      renderConfirm(msg.data);
      break;
    case "confirm.voice":
      renderConfirmVoice(msg.data);
      break;
    case "result":
      renderResult(msg.data);
      break;
    case "error":
      renderError(msg.data);
      break;
    case "artifact":
      onArtifact(msg.data);
      break;
    case "view":
      onView(msg.data);
      break;
    case "run.voice":
      onRunVoice(msg.data);
      break;
    case "followup":
      onFollowup(msg.data);
      break;
    case "presence":
      onPresence(msg.data);
      break;
    case "confirm.hold":
      onConfirmHold(msg.data);
      break;
    case "resume.offer":
      onResumeOffer(msg.data);
      break;
    case "runs":
      onRuns(msg.data);
      break;
  }
}

/** While listening: flag a mic that hears nothing, so silence isn't mistaken for "Swift is broken". */
function noteLevel(rms: number): void {
  if (state !== "listening") return;
  loudest = Math.max(loudest, rms);
  if (rms >= QUIET_LEVEL) delete transcriptEl.dataset.quiet;
  else if (loudest < QUIET_LEVEL && performance.now() - listenStarted > QUIET_MS) transcriptEl.dataset.quiet = "true";
}

function onStatus(status: ConnectionStatus): void {
  const was = connection.phase;
  connection = status;
  stage.dataset.backend = status.phase;
  if (status.phase === "connected") {
    // Clear a connection card, and say hello once per launch.
    if (was === "lost" || was === "failed") setStage("idle");
    if (!everConnected) window.setTimeout(renderReady, 400);
    everConnected = true;
    return;
  }
  const tooltip = { starting: "Swift: starting…", lost: "Swift: reconnecting…", failed: "Swift: stopped. Open the logs from this menu." }[status.phase];
  void invoke("set_status", { text: tooltip }).catch(() => {});
  if (status.phase === "failed") {
    // Reported once; the retries behind it stay quiet until something changes.
    if (was !== "failed") renderConnection(false);
  } else if (status.phase === "lost" && ACTIVE.has(state)) {
    // The run it was doing is gone with the connection.
    orb.stop();
    renderConnection(true);
  }
}

type HotkeyProblem = { name: string; spec: string; reason: "invalid" | "in_use"; detail: string };

async function registerHotkeys(hotkeys: Record<string, string>): Promise<void> {
  const wanted: Record<string, string> = {};
  if (hotkeys.push_to_talk) wanted.push_to_talk = hotkeys.push_to_talk;
  if (debugEnabled && hotkeys.debug) wanted.debug = hotkeys.debug;
  const problems = await invoke<HotkeyProblem[]>("register_hotkeys", { hotkeys: wanted });
  const ptt = problems.find((p) => p.name === "push_to_talk");
  if (ptt) {
    // Without push-to-talk Swift can't be used at all: this stays until dismissed.
    renderProblem({
      title: "Push-to-talk isn't working",
      message: ptt.reason === "in_use" ? `${hotkeyParts(ptt.spec).join("+")} is already used by another app.` : `“${ptt.spec}” isn't a shortcut Swift understands.`,
      hint: "Pick another shortcut for hotkeys.push_to_talk in config.yaml, then restart Swift.",
      detail: ptt.detail,
      sticky: true,
    });
  } else if (problems.length) {
    console.warn("hotkeys:", problems);
  }
  if (!readyReported) {
    // Startup time, once per launch: process start to "usable".
    readyReported = true;
    const t = await invoke<{ startup_ms: number; backend_ms: number | null }>("overlay_ready");
    client.send({ type: "ready", data: { startup_ms: Number(t.startup_ms), backend_ms: t.backend_ms === null ? null : Number(t.backend_ms) } });
  }
}

// ---- hotkeys from Rust -----------------------------------------------------------

void listen<{ name: string; state: "down" | "up" }>("hotkey", ({ payload }) => {
  if (payload.name === "escape" && payload.state === "down") {
    client.send({ type: "cancel", data: {} });
  } else if (payload.name === "debug" && payload.state === "down" && debugEnabled && !ACTIVE.has(state)) {
    // Ignored while busy (the backend would ignore it too), so the cycle doesn't skip a scenario.
    const scenario: Scenario = SCENARIOS[scenarioIndex++ % SCENARIOS.length];
    client.send({ type: "debug.run", data: { scenario } });
  } else if (payload.name === "push_to_talk") {
    const sent = client.send({ type: "ptt", data: { state: payload.state } });
    if (!sent && payload.state === "down") renderConnection(true);
    // Mid-run, the backend listens for "show me" / "stop" and reports it as run.voice (ADR-010 §6).
  }
});

void listen<{ inside: boolean }>("hover", ({ payload }) => setHover(payload.inside));
void listen("already-running", () => renderAlreadyRunning());
void listen<{ anchor: string }>("placement", ({ payload }) => setAnchor(payload.anchor));
void listen<boolean>("drag", ({ payload }) => {
  stage.dataset.dragging = String(payload);
  dragging = payload;
  setHold();
});

void invoke<{ anchor: string }>("get_placement").then((p) => setAnchor(p.anchor)).catch(() => {});
client.start();

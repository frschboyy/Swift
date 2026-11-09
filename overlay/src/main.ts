// Overlay renderer. The backend owns the state machine; this file draws it,
// forwards hotkeys, manages Esc registration and click-through regions. What is on screen and
// for how long is decided by the presenter (presenter.ts, ADR-013): no fade timers here.
// Failure cards, connection status, placement and dragging: ADR-009.
// Run artifacts and the "show me" detail view: ADR-010 §7. The detail view replaces the
// working card's body in place (the card never moves mid-run); Swift picks what it shows.
// Several requests (ADR-018, the Deck): the others are labelled edges behind the card (``runs``,
// deck.ts); a click on one, or the card in front fading while one still runs, brings it forward.
// ADR-015: the backend hears when a confirm card is actually on screen (``card.seen``): its countdown
// runs only then. Without pane windows (the dev harness), the stack is drawn beside the card.
// ADR-015 §9, §10 (the owner checks of 2026-10-27): what waits for the owner is a stack of cards in
// a bottom corner (stack.ts), and a hotkey or the tray opens a text box to type to Swift. Pane
// windows are opened and closed one change at a time, and a pane Swift doesn't want is closed
// whatever it shows.
//
// ADR-017, the owner's Capsule design (docs/design/swift-overlay): a small pill at the anchor is
// Swift's body (capsule.ts: heard, listening, working, speaking, not listening), and every card
// grows out of it. Cards: working (status and steps), answers (one line, paragraphs, a table, a
// long one opened in place), failed, stopped / not done in one row, the amber confirm card, Swift's
// question, and timers and reminders that stay until handled. Dark or light follows Windows.
//
// ADR-017 §7: a request's live view (live.ts). ``live`` items arrive for every request; "show
// me" (the backend's ``watch``) or Watch on the working card or an edge opens a pane window per
// request, beside the card. Without pane windows (the dev harness) it is drawn beside the card.

import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import { activityLabel, byline, handoffLabel } from "./agents";
import * as A from "./answer";
import * as Q from "./ask";
import * as C from "./capsule";
import { el, hotkeyParts, icon, keys, withKeys } from "./dom";
import { describeBackendProblem } from "./engine";
import { cardLines, hasMarkedLines } from "./cardtext";
import * as D from "./deck";
import { DeckDraw } from "./deckdraw";
import { BackendClient, type ConnectionStatus } from "./ipc";
import { Orb } from "./orb";
import { leaveTo, moveFrom } from "./shuffle";
import * as Panes from "./panes";
import * as H from "./heard";
import * as L from "./live";
import * as P from "./presenter";
import { SCENARIOS, type Activity, type Agent, type Artifact, type ErrorData, type Inbound, type ResultDetails, type Scenario, type UiState } from "./protocol";
import { wantsRaise } from "./raise";
import * as S from "./stack";
import { followTheme } from "./theme";
import * as V from "./views";

const INFO_FADE_MS = 5000;
const ERROR_FADE_MS = 12000;
// An error with "Try again" waits longer: the button is an answer the owner may want to give.
const RETRY_FADE_MS = 20000;
const READY_FADE_MS = 4000;
// Stopped / Not done: one row, gone after 4 s (the reply window can keep it longer).
const ROW_FADE_MS = 4000;
const MAX_STEPS = 5;
// Show the elapsed time once a run takes longer than this; say it's still going after STALL_MS without news.
const ELAPSED_AFTER_MS = 3000;
const STALL_MS = 20000;
const ACTIVE: ReadonlySet<UiState> = new Set(["listening", "transcribing", "working", "confirm"]);
// Failures where the log has the cause.
const LOGGED: ReadonlySet<string> = new Set(["internal", "crashed", "executor_failed", "service"]);

const stage = document.getElementById("stage")!;
const card = document.getElementById("card")!;
const rowsEl = document.getElementById("rows")!;
const capsuleEl = document.getElementById("capsule")!;
const capLabel = document.getElementById("cap-label")!;
const capSub = document.getElementById("cap-sub")!;
const capBtn = document.getElementById("cap-btn") as HTMLButtonElement;
const capRing = capsuleEl.querySelector<HTMLElement>(".cap-ring")!;
const orb = new Orb(capsuleEl);

/** The one state of the screen: what the presenter says is on it. Never kept apart from it, so a
 * frame the presenter ignored can't change it (review 2026-11-05, M3). */
const stageNow = (): UiState => P.stageOf(pres);
let steps: string[] = [];
let request = "";
// The request was typed (the card's keyboard icon), not said.
let typed = false;
// The live words on the capsule while listening.
let transcriptText = "";
// The provider working on the current run, and what it last reported doing.
let agent: Agent | null = null;
let current: { activity?: Activity; agent: Agent | null; subagent: boolean; app?: string | null } | null = null;
let runStarted = 0;
// A card coming forward from an edge: whose, and when its request really started.
let forward: D.Forward | null = null;
let lastStepAt = 0;
let compact = readPref("swift.compact") === "1";
let hovering = false;
let dragging = false;
// The answer on the card is opened with "Read more": it holds, like hover, until "Read less".
let expanded = false;
// What is on screen and until when (ADR-013 §3). Changed only through present*().
let pres: P.Presenter = P.initial;
// The last messages, for the debug-build invariant report.
const recent: string[] = [];
let escapeActive = false;
let debugEnabled = false;
let pttSpec = "";
let typeSpec = "";
let scenarioIndex = 0;
let lastRegions = "";
// Startup times, measured once per launch and reported to every backend this overlay connects to.
let readyTimes: { startup_ms: number; backend_ms: number | null } | null = null;
// The backend this overlay last talked to (``hello.ok`` instance): a new one put nothing on screen (O-02).
let backendInstance: string | null = null;
let connection: ConnectionStatus = { phase: "starting" };
let everConnected = false;
let listenStarted = 0;
let loudest = 0;
// Listening, and nothing above room noise for C.QUIET_MS: "I can't hear you".
let quietNow = false;
// Swift is talking (``speech``): the capsule says so, with Stop.
let speaking = false;
// Whether hands-free listening is on, and why not (``presence``).
let presence: Extract<Inbound, { type: "presence" }>["data"] | null = null;
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
// The "Listening…" pulse (heard.ts): the capsule's heard state until it fades.
let heardNow: H.Heard | null = null;
let heardTimer = 0;
const DRAFT_LINES = 8;
// A card that goes within this long of something joining the stack went there.
const HANDOFF_MS = 400;
// The confirm card the backend was last told is on screen (ADR-015 §4.2).
let seen: string | null = null;
// Pane windows (ADR-015 §3): what each open one shows. False once opening one failed: rows instead.
let paneWindows = true;
let reader: Panes.Reader = null;
// A working card with no news for a while collapses to its line (ADR-015 §3.3); the pointer on it opens it.
let quiet = false;
let lastLookAt = 0;
// The waiting stack (ADR-015 §9) and the text box (§10): null while closed.
let stack: S.Stack = S.initialStack;
// Where the stack's window is (its middle on the screen), and when something last joined it.
let stackAt: number | null = null;
let joinedStackAt = 0;
let stackSelected: string | null = null;
let typing: Panes.TypeView | null = null;
let typedDraft = "";
// The tray menu pane (ADR-017): null while closed.
let tray: Panes.TrayView | null = null;
// What each request's live view shows, and which are open (ADR-017 §7).
let live: L.Live = L.initialLive;
// The other requests, behind the card (ADR-018).
let deck: D.Deck = D.initialDeck;
// The answer on screen asked something (``followup`` with question): Swift's question card.
let question: { data: Extract<Inbound, { type: "result" }>["data"]; words: string; typed: boolean } | null = null;
// Swift's question while a request runs (ask.ts): shown on its working card until the backend closes it.
let asked: Q.Ask | null = null;
// Screen position of the last press on the card: a press that moved was a drag, not a click.
let pressAt: { x: number; y: number } | null = null;

const client = new BackendClient(onMessage, onStatus);

followTheme(stage, { invoke: (cmd) => invoke(cmd), listen: (event, handler) => listen(event, handler) });

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

function ico(name: string, cls: string): SVGSVGElement {
  const node = icon(name);
  node.classList.add(cls);
  return node;
}

// ---- the capsule (capsule.ts) ------------------------------------------------------------

/** Long live words: the end of them, which is what is being said now. */
const tail = (text: string, max = 60): string => (text.length <= max ? text : `…${text.slice(-max + 1).trimStart()}`);

function drawCapsule(): void {
  const paused = C.pausedBy(presence);
  const cardOpen = card.classList.contains("card--in") && !card.classList.contains("card--held");
  const p = C.presence({ state: stageNow(), heard: H.heardVisible(heardNow, stageNow(), Date.now()), quiet: quietNow, speaking, paused, cardOpen, asking: asked !== null });
  const elapsed = stageNow() === "working" && runStarted && Date.now() - runStarted > ELAPSED_AFTER_MS ? elapsedText() : "";
  const v = C.view(p, transcriptText, elapsed, paused);
  const was = capsuleEl.dataset.p;
  capsuleEl.dataset.p = p;
  stage.dataset.presence = p;
  if (capLabel.textContent !== v.label) capLabel.textContent = v.label;
  const sub = tail(v.sub);
  if (capSub.textContent !== sub) capSub.textContent = sub;
  if (was !== p) {
    capRing.replaceChildren(p === "paused-mic" ? icon("slash") : p === "paused-locked" ? icon("lock") : "");
    if (v.button === "stop") capBtn.replaceChildren(icon("stop"), "Stop", el("kbd", {}, "Esc"));
    else if (v.button === "resume") capBtn.replaceChildren(icon("play"), "Resume");
    capBtn.hidden = v.button === null;
    capBtn.dataset.action = v.button ?? "";
    capsuleEl.toggleAttribute("data-hit", v.clickable);
    scheduleRegions();
  }
}

capBtn.addEventListener("click", () => {
  if (capBtn.dataset.action === "stop") stopSpeaking();
  else if (capBtn.dataset.action === "resume") client.send({ type: "listen", data: { on: true } });
});

function stopSpeaking(): void {
  client.send({ type: "speech.stop", data: {} });
}

// ---- rendering ---------------------------------------------------------------

/** A new request: forget the last one's steps, artifacts and timers. */
function resetRun(keepRequest: boolean): void {
  steps = [];
  if (!keepRequest) {
    request = "";  // the transcript of a request that skipped "listening" arrived just before
    typed = false;
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
  question = null;
}

/** Debug builds: a broken presenter rule is reported with the messages that led to it. */
function checkPresenter(): void {
  syncStage();
  reportSeen();
  syncTypingNotice();
  if (!debugEnabled) return;
  const broken = P.violations(pres);
  if (broken.length) console.warn("[overlay] presenter rule broken:", broken, "after", recent.slice(-12));
}

/** The stage, Esc and the capsule follow the presenter, whatever changed it. */
function syncStage(): void {
  const now = stageNow();
  if (stage.dataset.state === now) return;
  stage.dataset.state = now;
  void syncEscape();
  drawCapsule();
}

/** The card's time bar and sticky state follow the presenter's deadline. */
function showDeadline(): void {
  const fadeAt = pres.card.fadeAt;
  card.classList.toggle("card--sticky", fadeAt === null && !ACTIVE.has(stageNow()));
  if (fadeAt !== null) card.style.setProperty("--fade-ms", `${Math.max(0, fadeAt - Date.now())}ms`);
  card.classList.toggle("card--paused", pres.pausedLeft !== null);
  // The confirm card's bar is its countdown, the question card's is in its pill: not this one.
  const own = card.classList.contains("card--confirm") || card.classList.contains("card--question");
  const bar = card.querySelector<HTMLElement>(":scope > .timebar");
  if (bar && !own) bar.hidden = fadeAt === null;
}

/** An answer, error or notice is being drawn: ``false`` means it mustn't be (busy screen, or stale). */
function presentAnswer(kind: "result" | "error" | "notice", ms: number | null, runId?: string, threadId?: string, summary?: string): boolean {
  const r = P.onAnswer(pres, { kind, runId, threadId, summary, ms }, Date.now());
  pres = r.p;
  checkPresenter();
  return r.shown;
}

/** Tell the backend which confirm card is on screen: it counts down only while one is (ADR-015 §4.2),
 * and only while the owner is here (ADR-017). */
function reportSeen(): void {
  const now = P.seenCard(pres);
  if (now === seen) return;
  if (seen) client.send({ type: "card.seen", data: { request_id: seen, visible: false } });
  if (now) client.send({ type: "card.seen", data: { request_id: now, visible: true } });
  seen = now;
}

// ---- other requests: edges behind the card (ADR-018) ----------------------------------

const ROW_STATE: Record<string, string> = {
  queued: "Waiting to start",
  idle: "Starting",
  listening: "Listening",
  transcribing: "Transcribing",
  confirm: "Needs your OK",
  // Swift asked and listens for the answer: never "Working on it" (owner check 144, 2026-11-09).
  asking: "Waiting for your answer",
  result: "Ready to read",
  error: "Didn't finish",
  done: "Stopped",
};

function onRuns(data: Extract<Inbound, { type: "runs" }>["data"]): void {
  const rows: P.Row[] = data.rows.map((r) => ({
    runId: r.run_id, threadId: r.thread_id, title: r.title, state: r.state, activity: r.activity, app: r.app,
    startedMs: r.started_ms, summary: r.summary, words: r.words,
  }));
  // The card on screen, if this sends it behind: its edge starts there.
  const onCard = pres.focus ?? pres.card.runId;
  if (onCard && onCard !== data.focus && card.classList.contains("card--in")) deckDraw.frontLeaving(onCard, card.getBoundingClientRect());
  // Another request's card comes next: its words and its clock, and nothing left of the last one's.
  const words = D.wordsComingForward(pres.rows, onCard, data.focus);
  if (words !== null) {
    const started = pres.rows.find((r) => r.runId === data.focus)!.startedMs;
    resetRun(true);
    request = words;
    typed = false;
    forward = { runId: data.focus!, startedMs: started };
  }
  pres = P.onRuns(pres, data.focus, rows, data.waiting);
  checkPresenter();
  setLive(L.onRows(live, rows, Date.now()));
  if (pres.focus !== promoted) promoted = null;
  deck = D.onRows(deck, pres.focus, pres.rows, Date.now(), onCard);
  window.setTimeout(drawRows, D.EDGE_DELAY_MS);  // a young request's edge is due then...
  window.setTimeout(drawRows, D.EDGE_DELAY_MS + D.ACK_MS + 20);  // ...and settles then
  drawRows();
}

function rowLabel(r: P.Row): string {
  if (r.state === "working") return activityLabel(null, (r.activity ?? undefined) as Activity | undefined, false, r.app);
  const label = ROW_STATE[r.state] ?? "Working on it";
  return r.summary && (r.state === "error" || r.state === "done") ? `${label}: ${r.summary}` : label;
}

const deckDraw = new DeckDraw({
  list: rowsEl,
  label: rowLabel,
  focus: askFocus,
  watch: (r) => openLive(r.runId, r.title, r.words ?? ""),
  unfold: () => card.querySelector<HTMLElement>('.link[aria-expanded="true"]')?.click(),
  landingFrom: () => capsuleEl.getBoundingClientRect(),
});

/** The one way the other requests are drawn: the harness shows what the owner sees. */
function drawRows(): void {
  const view = D.deckView(deck, pres.rows, Date.now(), expanded);
  // The card gives way, so it never pushes the deck off the window.
  stage.style.setProperty("--deck-h", `${view.height}px`);
  deckDraw.draw(view, D.keyOf(deck, pres.focus));
  scheduleRegions();
}

/** The panes wanted now: the reader, the stack, the text box, the tray menu and the live views. */
const wanted = (): Panes.PaneSpec[] => {
  const view = S.stackView(stack, Date.now());
  return Panes.wantedPanes(reader, {
    stack: view && { ...view, mainX: Math.round(window.screenX + window.innerWidth / 2) }, typing, tray, live: L.openRuns(live).map(L.view),
  });
};

// One change at a time, and a window nobody wants is closed even if it opened late (bug 1).
const paneSync = new Panes.PaneSync(
  {
    open: (spec) => {
      const { w, h } = Panes.paneSize(spec);
      // The text box opens clear of the card on screen ("Change" on a confirm card, owner checks 2026-11-04).
      const r = spec.kind === "type" && card.classList.contains("card--in") ? card.getBoundingClientRect() : null;
      const edges = rowsEl.hidden ? r : rowsEl.getBoundingClientRect();  // the deck is part of the card
      const at = r && edges && r.height > 0 ? [Math.min(r.top, edges.top), Math.max(r.bottom, edges.bottom)] : null;
      return invoke("open_pane", { label: spec.label, kind: spec.kind, index: spec.index, w, h, card: at });
    },
    close: (label) => void invoke("close_pane", { label }).catch(() => {}),
    send: (label, view) => sendPane(label, view),
  },
  wanted,
  (err) => {
    // No pane windows here (the dev harness, or an older shell): the stack beside the card instead.
    console.warn("[overlay] pane windows unavailable:", err);
    paneWindows = false;
    reader = null;
    typing = null;
    tray = null;
    drawRows();
    drawStackInline();
    drawLiveInline();
  },
);
const panes = paneSync.shown;

/** Open, update and close pane windows to match the presenter, the reader, the stack and the text box. */
function syncPanes(): Promise<void> {
  return paneWindows ? paneSync.sync() : Promise.resolve();
}

/** A pane window Swift doesn't want (left over from an older shell or a lost close): closed. */
async function sweepPanes(): Promise<void> {
  if (!paneWindows || paneSync.busy) return;
  try {
    for (const label of paneSync.strays(await invoke<string[]>("pane_labels"))) {
      void invoke("close_pane", { label }).catch(() => {});
    }
  } catch {
    // An older shell without pane_labels: nothing to sweep.
  }
}

function sendPane(label: string, view: Panes.PaneView): void {
  void emitTo(label, "pane", { label, view }).catch(() => {});
}

type PaneAction = {
  label: string; action: string; runId?: string; id?: string; item?: "open" | "skip" | "end"; text?: string; value?: string;
};

void listen<PaneAction>("pane-action", ({ payload }) => {
  switch (payload.action) {
    case "ready": {
      const view = panes.get(payload.label);
      if (view) sendPane(payload.label, view);
      else void invoke("close_pane", { label: payload.label }).catch(() => {});  // nothing for it to show
      break;
    }
    case "stack-expand":
      stack = S.expand(stack);
      void syncEscape();
      void syncPanes();
      break;
    case "stack-collapse":
      collapseStack();
      break;
    case "stack-at":
      stackAt = Number(payload.value);
      break;
    case "stack-item":
      if (payload.id && payload.item) stackAction(payload.id, payload.item);
      break;
    case "type-send":
      typedDraft = "";
      if (payload.text?.trim()) client.send({ type: "text", data: { text: payload.text, thread_id: typing?.follows ? typingThread : null } });
      closeTyping();
      break;
    case "type-close":
      typedDraft = payload.text ?? typedDraft;
      closeTyping();
      break;
    case "live-close":
    case "live-stop":
    case "live-app":
    case "live-answer":
    case "live-touch":
      if (payload.runId) liveAction(payload.action, payload.runId);
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
    case "tray":
      void trayAction(payload.value ?? "", payload.text);
      break;
  }
});

function collapseStack(): void {
  stack = S.collapse(stack);
  void syncEscape();
  void syncPanes();
  drawStackInline();
}

/** Open, skip or end something in the waiting stack (or the card on screen, from its buttons). */
function stackAction(id: string, action: "open" | "skip" | "end"): void {
  stack = S.afterAction(stack, action);
  client.send({ type: "stack.action", data: { id, action } });
  void syncEscape();
  void syncPanes();
  drawStackInline();
}

/** Without pane windows (the dev harness): the stack is drawn under the card, as its pane would. */
const stackEl = document.getElementById("stack");
function drawStackInline(): void {
  if (!stackEl) return;
  const view = paneWindows ? null : S.stackView(stack, Date.now());
  stackEl.hidden = !view;
  if (!view) {
    stackEl.replaceChildren();
    scheduleRegions();
    return;
  }
  let lastClick = 0;
  stackEl.replaceChildren(
    view.expanded
      ? el("div", { "data-hit": true }, V.stackOpen(view, {
          item: stackAction, collapse: collapseStack, selected: stackSelected, unfold: !stackEl.querySelector(".stack-open"),
          select: (id) => { stackSelected = id; for (const row of stackEl.querySelectorAll<HTMLElement>(".stack-row")) row.setAttribute("aria-selected", String(row.dataset.id === id)); },
        }))
      : el("div", { "data-hit": true }, V.stackClosed(view, {
          tabindex: "0",
          onclick: () => {
            const now = Date.now();
            if (now - lastClick < 450) {
              stack = S.expand(stack);
              void syncEscape();
              drawStackInline();
            }
            lastClick = now;
          },
        })),
  );
  scheduleRegions();
}

function onStackMessage(items: S.Stack["items"]): void {
  const before = new Set(stack.items.map((i) => i.id));
  if (items.some((i) => !before.has(i.id))) joinedStackAt = Date.now();
  stack = S.onStack(stack, items, Date.now());
  void syncEscape();
  void syncPanes();
  drawStackInline();
}

// ---- typing to Swift (ADR-015 §10) ----------------------------------------------------------

// The conversation the open text box follows up (the one on screen when it opened).
let typingThread: string | null = null;

/** A confirm card is open (and on screen): the text box says typing can't approve it. */
const confirmOpen = (): boolean => pres.pendingConfirm !== null && pres.held === null;

/** The hotkey or the tray: open the text box (or close it, if it's open). */
function toggleTyping(): void {
  if (typing) {
    closeTyping();
    return;
  }
  const onScreen = ["result", "error", "confirm", "working"].includes(pres.card.kind) ? pres.card.threadId ?? pres.threadId : null;
  typingThread = onScreen;
  const follows = onScreen && pres.lastAnswer?.threadId === onScreen ? pres.lastAnswer.text : null;
  typing = { kind: "type", draft: typedDraft, follows, confirm: confirmOpen() };
  if (!paneWindows) {
    // The dev harness has no pane windows: a prompt stands in for the text box.
    const text = window.prompt(confirmOpen() ? "Type a change (typing can't approve)" : "Type to Swift");
    typing = null;
    if (text?.trim()) client.send({ type: "text", data: { text, thread_id: follows ? onScreen : null } });
    return;
  }
  void syncEscape();  // Esc belongs to the text box while it's open
  void syncPanes();
}

/** The box's "Typing can't approve" row follows the confirm card. */
function syncTypingNotice(): void {
  if (!typing || !!typing.confirm === confirmOpen()) return;
  typing = { ...typing, confirm: confirmOpen() };
  void syncPanes();
}

function closeTyping(): void {
  if (!typing) return;
  typing = null;
  typingThread = null;
  void syncEscape();
  void syncPanes();
}

// ---- the live view of a request (ADR-017 §7) -----------------------------------------------

function setLive(next: L.Live): void {
  if (next === live) return;
  const watched = (l: L.Live): boolean => !!pres.runId && !!L.find(l, pres.runId)?.open;
  const toggled = watched(next) !== watched(live);
  live = next;
  if (toggled && stageNow() === "working") renderWorking();  // its Watch button comes and goes
  if (paneWindows) void syncPanes();
  else drawLiveInline();
}

/** Watch: the live view of a request, beside the card. The backend hears of it for the log only. */
function openLive(runId: string, title: string, words: string): void {
  setLive(L.watch(live, runId, title, words, Date.now()));
  client.send({ type: "watch", data: { run_id: runId, open: true } });
}

function liveAction(action: string, runId: string): void {
  const r = L.find(live, runId);
  switch (action) {
    case "live-close":
      setLive(L.close(live, runId));
      client.send({ type: "watch", data: { run_id: runId, open: false } });
      break;
    case "live-stop":
      client.send({ type: "run.stop", data: { run_id: runId } });
      break;
    case "live-app":
      client.send({ type: "live.app", data: { run_id: runId } });
      break;
    case "live-touch":
      setLive(L.touch(live, runId, Date.now()));
      break;
    case "live-answer":
      // The whole answer when this window had it (the request in front); else that request forward.
      if (r?.ended && (r.ended.details || runId === pres.runId)) {
        if (paneWindows) {
          reader = Panes.openReader(r.title, r.ended.summary, r.ended.details, runId, Date.now());
        } else askFocus(runId);
      } else askFocus(runId);
      setLive(L.close(live, runId));
      client.send({ type: "watch", data: { run_id: runId, open: false } });
      break;
  }
}

/** Without pane windows (the dev harness): the open live views beside the card. */
const liveEl = document.getElementById("live");
function drawLiveInline(): void {
  if (!liveEl) return;
  const views = paneWindows ? [] : L.openRuns(live).map(L.view);
  liveEl.hidden = views.length === 0;
  const tops = new Map([...liveEl.querySelectorAll<HTMLElement>("[data-run]")].map((n) => [n.dataset.run, n.querySelector<HTMLElement>(".live-body")?.scrollTop ?? 0]));
  const docs = new Map([...liveEl.querySelectorAll<HTMLElement>("[data-run] .live-doc")].map((d) => [d.closest<HTMLElement>("[data-run]")!.dataset.run,
    d.scrollHeight - d.scrollTop - d.clientHeight < 24 ? null : d.scrollTop]));
  liveEl.replaceChildren(...views.map((v) => {
    const node = el("div", { "data-hit": true, "data-run": v.runId }, V.liveCard(v, {
      close: () => liveAction("live-close", v.runId),
      stop: () => liveAction("live-stop", v.runId),
      link: (url) => void invoke("open_link", { url }).catch(() => window.open(url, "_blank", "noopener")),
      app: () => liveAction("live-app", v.runId),
      answer: () => liveAction("live-answer", v.runId),
    }));
    return node;
  }));
  for (const node of liveEl.querySelectorAll<HTMLElement>("[data-run]")) {
    const body = node.querySelector<HTMLElement>(".live-body");
    if (body) body.scrollTop = tops.get(node.dataset.run) ?? 0;
    // What is being written follows its newest paragraph, unless the owner scrolled up in it.
    const doc = node.querySelector<HTMLElement>(".live-doc");
    const kept = docs.get(node.dataset.run);
    if (doc) doc.scrollTop = kept ?? doc.scrollHeight;
  }
  scheduleRegions();
}

function askFocus(runId: string): void {
  promoted = runId;
  client.send({ type: "focus", data: { run_id: runId } });
}

// ---- the tray menu (ADR-017) --------------------------------------------------------------------

/** One line for the tray: whether Swift is listening, and why not. */
function trayStatus(): string {
  if (connection.phase === "starting") return "Starting…";
  if (connection.phase === "lost") return "Reconnecting…";
  if (connection.phase === "failed") return "Stopped. The logs say why.";
  const paused = C.pausedBy(presence);
  if (paused === "mic") return "Not listening · Mic off";
  if (paused === "locked") return "Not listening · Screen locked";
  if (paused === "asleep") return "Not listening · PC was asleep";
  if (presence?.wake && presence.listening) return "Listening for “Hey Swift”";
  return `Hold ${pttText()} to talk`;
}

async function openTray(): Promise<void> {
  if (!paneWindows) return;
  try {
    const prefs = await invoke<{ anchor: string; smart: boolean }>("get_prefs");
    tray = { kind: "tray", status: trayStatus(), paused: !!presence?.paused, anchor: prefs.anchor, smart: prefs.smart, typeKey: typeSpec || null };
  } catch {
    return;  // an older shell: its native menu
  }
  void syncPanes();
}

function refreshTray(): void {
  if (!tray) return;
  tray = { ...tray, status: trayStatus(), paused: !!presence?.paused };
  void syncPanes();
}

async function trayAction(op: string, value?: string): Promise<void> {
  switch (op) {
    case "anchor":
      if (value) await invoke("set_anchor", { anchor: value }).catch(() => {});
      if (tray && value) tray = { ...tray, anchor: value };
      break;
    case "smart": {
      const on = !(tray?.smart ?? true);
      await invoke("set_smart", { on }).catch(() => {});
      if (tray) tray = { ...tray, smart: on };
      break;
    }
    case "pause":
      client.send({ type: "listen", data: { on: !!presence?.paused } });
      tray = null;
      break;
    case "type":
      tray = null;
      toggleTyping();
      break;
    case "settings":
      tray = null;
      void invoke("open_settings").catch(() => {});
      break;
    case "restart":
      tray = null;
      restartSwift();
      break;
    // Saved recordings (audit B-06): the backend answers with a card.
    case "improve":
      tray = null;
      client.send({ type: "recordings", data: { action: "improve" } });
      break;
    case "clear-recordings":
      tray = null;
      client.send({ type: "recordings", data: { action: "clear" } });
      break;
    case "quit":
      void invoke("quit_app").catch(() => {});
      return;
    default:
      tray = null;  // closed (a click outside it)
  }
  void syncPanes();
}

void listen("tray-open", () => {
  if (tray) {
    tray = null;
    void syncPanes();
  } else void openTray();
});
// The native menu (right click): the same actions.
void listen<string>("tray-action", ({ payload }) => void trayAction(payload));

// ---- cards -----------------------------------------------------------------------------------

/** Earlier turns of this conversation, one line each, above the card (ADR-013 §4.2). */
function threadLines(): HTMLElement | null {
  if (!pres.history.length) return null;
  return el("ul", { class: "thread", "aria-label": "Earlier in this conversation" }, ...pres.history.map((t) => el("li", {}, t.text)));
}

function setStage(next: UiState, runId: string | null = null, threadId: string | null = null): void {
  const change = P.onState(pres, next, runId, threadId);
  if (change.ignored) return;  // another request's news: its edge says it
  pres = change.p;
  checkPresenter();
  if (next === "result" || next === "error") {
    // Only announces its answer, which sets the card (or is refused) when it comes.
    if (!runId || runId === pres.card.runId) orb.stop();
    return;
  }
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
    quietNow = false;
    transcriptText = "";
    card.replaceChildren();
    card.className = "card";
    card.removeAttribute("data-hit");
  }
  if (next === "working") {
    if (!runStarted) {
      lastStepAt = Date.now();
      runStarted = D.clockStart(forward, runId, lastStepAt);
      forward = null;
    }
    renderWorking();
  }
  if (next === "idle") hideCard();
  drawCapsule();
}

function showCard(node: HTMLElement, variant: string, role: "status" | "alert" = "status"): void {
  // A new card: whatever was opened with "Read more" is gone with the old one.
  if (expanded && !node.querySelector(".answer--open")) setExpanded(false);
  card.className = `card ${variant.split(" ").map((v) => (v.startsWith("card--") ? v : `card--${v}`)).join(" ")} card--in${hovering ? " card--hover" : ""}`;
  card.setAttribute("role", role);
  card.setAttribute("data-hit", "");
  card.replaceChildren(node, el("span", { class: "timebar", "aria-hidden": "true" }));
  for (const anim of card.getAnimations()) anim.cancel();  // on its way back into the capsule
  // It was an edge just now: one body, so the card grows out of it.
  const from = deckDraw.takeForward(D.keyOf(deck, pres.card.runId), Date.now());
  if (from) moveFrom(card, from);
  drawCapsule();
  // Scrolling a card that didn't fit holds it, like scrolling a long answer.
  node.addEventListener("scroll", () => noteScroll(), { passive: true });
  scheduleRegions();
}

/** Where a card goes as it leaves: towards the stack if it has just joined it (a handoff between
 * windows, ADR-018 §3), otherwise back into the capsule it grew out of. */
function leavingFor(): DOMRect {
  if (stackAt === null || Date.now() - joinedStackAt > HANDOFF_MS) return capsuleEl.getBoundingClientRect();
  const r = card.getBoundingClientRect();
  const toward = stackAt < window.screenX + window.innerWidth / 2 ? -1 : 1;
  return new DOMRect(r.left + toward * 48, r.top, r.width, r.height);
}

function hideCard(): void {
  const shown = card.classList.contains("card--in");
  card.classList.remove("card--in");
  card.classList.add("card--out");
  card.removeAttribute("data-hit");
  drawCapsule();
  scheduleRegions();
  const clear = (): void => {
    if (!card.classList.contains("card--out")) return;
    card.replaceChildren();
    card.className = "card";
    scheduleRegions();
  };
  if (shown) leaveTo(card, leavingFor(), clear);
  else clear();
}

function dismiss(): void {
  const r = P.onDismiss(pres);
  pres = r.p;
  if (r.hide) setStage("idle");
}

/** Head row: how it was asked (mic or keyboard) · the owner's words · close. The whole card drags. */
function headRow(close: (() => void) | null = dismiss, label = "Close"): HTMLElement {
  return el(
    "header",
    { class: "card-head" },
    ico(typed ? "keyboard" : "mic", "head-icon"),
    el("p", { class: "words", title: request }, request ? `“${request}”` : ""),
    close ? el("button", { class: "icon-btn", "aria-label": label, title: label, onclick: (ev: Event) => { ev.stopPropagation(); close(); } }, icon("x")) : null,
  );
}

function elapsedText(): string {
  const s = Math.floor((Date.now() - runStarted) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The working card shrinks to one line (its × , or no news for a while); the pointer opens it again. */
function shrinkWorking(): void {
  quiet = true;
  renderWorking();
}

function renderWorking(): void {
  if (Q.askVisible(asked, stageNow(), pres.focus)) {
    renderAsk(asked!);
    return;
  }
  const busyAt = Date.now();
  // A new step re-renders the card: keep the reader's place in an open draft.
  const scrolled = card.querySelector<HTMLElement>(".draft-body")?.scrollTop ?? 0;
  const title = current ? activityLabel(current.agent, current.activity, current.subagent, current.app) : handoffLabel(agent);
  const elapsed = el("span", { class: "elapsed", "aria-hidden": "true" }, runStarted && busyAt - runStarted > ELAPSED_AFTER_MS ? elapsedText() : "");
  // "Show me" on the steps (viewing null) opens them even in compact mode.
  const shown = viewing ? artifacts.get(viewing) : undefined;
  const small = (compact || quiet) && viewing === undefined;
  if (small) {
    showCard(
      el("div", { class: "card-in row-line" },
        el("span", { class: "spinner", "aria-hidden": "true" }),
        el("span", { class: "row-word", "aria-live": "polite" }, title),
        el("span", { class: "row-desc" }, request ? `“${request}”` : ""),
        elapsed,
        el("button", { class: "icon-btn", "aria-label": "Show the steps", title: "Show the steps", onclick: (ev: Event) => {
          ev.stopPropagation();
          quiet = false;
          compact = false;
          writePref("swift.compact", "0");
          lastLookAt = Date.now();
          renderWorking();
        } }, icon("expand"))),
      "working card--row",
    );
    return;
  }
  const stalled = isStalled(busyAt);
  const list = el("ol", { class: "steps" });
  steps.forEach((text, i) => {
    const latest = i === steps.length - 1;
    list.append(el("li", { class: latest ? "step step--now" : "step" }, icon(latest ? "play" : "check"), el("span", { class: "step-text" }, text)));
  });
  const showButton = artifacts.size && !shown
    ? el("button", { class: "btn btn--ghost", title: "Show what Swift is working on", onclick: () => askView("show") }, icon("external"), "Show")
    : null;
  const backButton = shown ? el("button", { class: "btn btn--ghost", onclick: () => askView("hide") }, "Back to steps") : null;
  showCard(
    el(
      "div",
      { class: "card-in" },
      headRow(shrinkWorking, "Shrink to one line"),
      threadLines(),
      el("div", { class: "status" }, el("span", { class: "spinner", "aria-hidden": "true" }), el("span", { class: "status-verb", "aria-live": "polite" }, title), elapsed),
      shown ? artifactView(shown) : steps.length ? list : null,
      stalled ? el("p", { class: "note" }, "Still working. Bigger requests can take a few minutes.") : null,
      runVoice ? runVoiceLine(runVoice) : null,
      el(
        "footer",
        { class: "card-foot" },
        el("span", { class: "hint foot-gap" }, el("kbd", {}, "Esc"), "stops"),
        backButton ?? showButton,
        pres.runId && !L.find(live, pres.runId)?.open
          ? el("button", { class: "btn btn--ghost", title: "Watch it work: sources, notes and what it writes", onclick: () => openLive(pres.runId!, request, request) }, icon("play"), "Watch")
          : null,
        el("button", { class: "btn btn--ghost", onclick: () => cancelRun() }, icon("stop"), "Stop"),
      ),
    ),
    "working",
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
        ? el("ul", { class: "result-list" }, ...candidates.map((p, i) => el("li", { class: i === chosen ? "chosen" : "" }, `${p.name} <${p.email}>` + (p.detail ? ` · ${p.detail}` : ""))))
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
          ? el("dl", { class: "kv" }, el("dt", {}, "To"), el("dd", {}, draft.data.to.map((p) => p.name || p.email).join(", ")), el("dt", {}, "Subject"), el("dd", {}, draft.data.subject))
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
  return el("section", { class: "artifact", role: "region", "aria-label": label }, titled ? el("h3", { class: "artifact-title" }, label) : null, body);
}

/** After the run: "show me" (or Show) on a result opens the artifact as its own card. */
function renderArtifactCard(a: Artifact): void {
  if (!presentAnswer("result", A.readingMs(a.kind === "email_draft" ? a.data.body : a.title), a.run_id, pres.threadId ?? undefined)) return;
  showCard(
    el("div", { class: "card-in", onclick: dismissUnlessControl }, headRow(), el("p", { class: "answer-note" }, a.title), artifactView(a, 0, false)),
    "result",
  );
  showDeadline();
}

function onArtifact(a: Artifact): void {
  const known = artifacts.get(a.id);
  if (known && known.version >= a.version) return; // late or repeated
  const first = artifacts.size === 0;
  artifacts.set(a.id, a);
  if (stageNow() === "working" && (first || viewing === a.id)) renderWorking();
}

function onView(v: Extract<Inbound, { type: "view" }>["data"]): void {
  if (stageNow() === "confirm" && lastConfirm) {
    // On the send card the draft is already there: "show me" opens all of it.
    fullDraft = v.open;
    renderConfirm(lastConfirm);
    return;
  }
  if (stageNow() === "working") {
    viewing = v.open ? v.artifact_id : undefined;
    renderWorking();
    return;
  }
  const a = v.artifact_id ? artifacts.get(v.artifact_id) : undefined;
  if (v.open && a && (stageNow() === "result" || stageNow() === "error" || stageNow() === "idle")) renderArtifactCard(a);
  else if (!v.open && card.querySelector(".artifact")) setStage("idle");
}

// ---- presence: whether Swift is listening, and why not (ADR-014 §8, ADR-017) -------------------

function onPresence(p: Extract<Inbound, { type: "presence" }>["data"]): void {
  presence = p;
  const hold = `Hold ${pttText()} to talk.`;
  let text = `Swift: ready. ${hold}`;
  if (p.paused) text = `Swift: not listening (paused from the tray). ${hold}`;
  else if (p.wake && p.listening) text = `Swift: listening for “hey Swift”. Or ${hold.toLowerCase()}`;
  else if (p.wake && p.reason === "locked") text = "Swift: paused while the screen is locked.";
  else if (p.wake && p.reason === "asleep") text = "Swift: paused (the PC was asleep).";
  void invoke("set_status", { text }).catch(() => {});
  // A confirm countdown runs only while the owner is here.
  const before = pres.away;
  pres = P.onPresent(pres, p.state === "here", Date.now());
  checkPresenter();
  if (before !== pres.away && stageNow() === "confirm" && lastConfirm) renderConfirm(lastConfirm);
  drawCapsule();
  refreshTray();
}

// ---- follow-up window: reply without the wake phrase, just after an answer ---------------

function onFollowup(data: Extract<Inbound, { type: "followup" }>["data"]): void {
  // The presenter keeps the answer up at least as long as Swift listens for a reply.
  pres = P.onFollowup(pres, data.open, data.seconds, Date.now());
  showDeadline();
  if (data.open && data.question && lastResult && (stageNow() === "result") && pres.card.runId === lastResult.run_id) {
    // The answer asked something: it becomes Swift's question card.
    question = { data: lastResult, words: request, typed };
  }
  if (question) renderQuestion();
  drawFollowup(pres.followupUntil ? Math.ceil((pres.followupUntil - Date.now()) / 1000) : 0);
}

function drawFollowup(left: number): void {
  if (question) {
    const time = card.querySelector<HTMLElement>(".q-pill .elapsed");
    if (time) time.textContent = `0:${String(Math.max(0, left)).padStart(2, "0")}`;
    return;
  }
  let line = card.querySelector<HTMLElement>(".followup");
  if (left <= 0 || (stageNow() !== "result" && stageNow() !== "error")) {
    line?.remove();
    return;
  }
  if (!line) {
    line = el("p", { class: "voice-hint followup", "data-phase": "listening", "aria-live": "off" });
    const foot = card.querySelector(".card-foot");
    if (foot) foot.before(line);
    else (card.firstElementChild ?? card).append(line);
    scheduleRegions();
  }
  line.replaceChildren(icon("mic"), `Listening for a reply · ${left} s`);
}

function onRunVoice(v: Extract<Inbound, { type: "run.voice" }>["data"]): void {
  window.clearTimeout(runVoiceTimer);
  runVoice = v.phase === "idle" ? null : v;
  // A hint stays long enough to read, then the card goes back to normal.
  if (v.phase === "hint") runVoiceTimer = window.setTimeout(() => { runVoice = null; if (stageNow() === "working") renderWorking(); }, 4000);
  if (stageNow() === "working") renderWorking();
  else if (v.phase === "hint" && (stageNow() === "result" || stageNow() === "error")) hintOnAnswer(v.text);
}

/** Said to an answer on the card, about the requests behind it ("Stopped …", "Which one?"): a line on it. */
function hintOnAnswer(text: string): void {
  card.querySelector(".answer-hint")?.remove();
  const line = el("p", { class: "voice-hint answer-hint", "data-phase": "hint", "aria-live": "polite" }, text);
  const foot = card.querySelector(".card-foot");
  if (foot) foot.before(line);
  else (card.firstElementChild ?? card).append(line);
  window.setTimeout(() => { line.remove(); scheduleRegions(); }, 4000);
  scheduleRegions();
}

function cancelRun(): void {
  client.send({ type: "cancel", data: {} });
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
}

// ---- the confirm card: solid, amber, its own countdown (ADR-017) ---------------------------------

const countdownText = (ms: number): string => {
  const s = Math.ceil(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** What the card asks to do, as facts: an event (or its change), an email, or the request's own detail. */
function confirmFacts(data: Extract<Inbound, { type: "confirm.request" }>["data"], shown: Artifact | undefined): HTMLElement | null {
  if (shown?.kind === "calendar_event") {
    const e = shown.data;
    const b = e.before;
    if (b && !e.removing) {
      const rows: [string, string, string][] = [];
      if (b.title !== e.title) rows.push(["What", b.title, e.title]);
      if (b.when !== e.when) rows.push(["When", b.when, e.when]);
      if ((b.location || "") !== (e.location || "")) rows.push(["Where", b.location || "–", e.location || "–"]);
      if ((b.attendees || "") !== (e.attendees || "")) rows.push(["Who", b.attendees || "–", e.attendees || "–"]);
      return el(
        "dl",
        { class: "facts facts--change" },
        el("dt", {}), el("dd", { class: "col-head" }, "Now"), el("dd", {}), el("dd", { class: "col-head" }, "After"),
        ...rows.flatMap(([k, was, now]) => [el("dt", {}, k), el("dd", { class: "was" }, was), el("dd", { class: "arrow", "aria-label": "becomes" }, "→"), el("dd", { class: "now" }, now)]),
        ...(rows.length ? [] : [el("dt", {}, "What"), el("dd", { class: "wide key" }, e.title)]),
        ...(Array.isArray(e.changes) && e.changes.length ? [el("p", { class: "facts-note" }, e.changes.join(" · "))] : []),
      );
    }
    return el(
      "dl",
      { class: "facts" },
      el("dt", {}, "What"), el("dd", { class: `key${e.removing ? " was" : ""}` }, e.title),
      el("dt", {}, "When"), el("dd", {}, e.when),
      ...(e.location ? [el("dt", {}, "Where"), el("dd", {}, e.location)] : []),
      ...(e.attendees ? [el("dt", {}, "Invites"), el("dd", {}, e.attendees)] : []),
      ...(e.meet ? [el("dt", {}, "Also"), el("dd", {}, "Adds a Google Meet link")] : []),
    );
  }
  if (shown?.kind === "email_draft") {
    const d = shown.data;
    const long = d.body.split("\n").length > DRAFT_LINES;
    return el(
      "dl",
      { class: "facts" },
      el("dt", {}, "To"), el("dd", { class: "key" }, d.to.map((p) => (p.name ? `${p.name} <${p.email}>` : p.email)).join(", ")),
      el("dt", {}, "Subject"), el("dd", {}, d.subject),
      el("div", { class: `mail-body${fullDraft ? " mail-body--full" : ""}`, tabindex: "0", role: "document", "aria-label": "The email" }, d.body),
      long ? el("button", { class: "link link--quiet wide", "aria-expanded": String(fullDraft), onclick: () => askView(fullDraft ? "hide" : "show") }, fullDraft ? "Show less" : "Show the whole email") : null,
    );
  }
  if (shown) return el("div", { class: "facts" }, el("div", { class: "facts-text" }, artifactView(shown, 0, false)));
  // A request's own detail (a command, a file): all of it, exactly as it will run (audit A-12).
  if (!data.detail) return null;
  const mono = /[\\/`$|;]|\s--?\w/.test(data.detail);
  const box = hasMarkedLines(data.tool)
    ? el("div", { class: "facts-text facts-text--mono" }, ...cardLines(data.detail).map((line) =>
      el("div", { class: line.agent ? "facts-line--agent" : "facts-line" }, line.text || " ")))
    : el("p", { class: `facts-text${mono ? " facts-text--mono" : ""}` }, data.detail);
  return el("div", { class: "facts" }, box, moreBelow(box));
}

/** Says there's more until the end has been reached: what's out of view must not look like the end (X-17).
 * Shown from the start, so a card that can't measure itself still says it. */
function moreBelow(box: HTMLElement): HTMLElement {
  const sign = el("p", { class: "facts-more" }, "More below: scroll to read all of it");
  const update = () => { sign.hidden = box.scrollHeight - box.scrollTop - box.clientHeight < 4; };
  box.addEventListener("scroll", update);
  requestAnimationFrame(update);
  return sign;
}

function renderConfirm(data: Extract<Inbound, { type: "confirm.request" }>["data"]): void {
  const reply = (decision: "approve" | "reject") => () => {
    // A stray click just as the card appears isn't an answer (ADR-017: 400 ms).
    if (decision === "approve" && !P.approveReady(pres, Date.now())) return;
    client.send({ type: "confirm.reply", data: { request_id: data.request_id, decision } });
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  };
  // A re-render (show me / hide on the card) keeps the deadline it already had.
  const again = lastConfirm?.request_id === data.request_id;
  if (!again) fullDraft = false;
  lastConfirm = data;
  // Redrawn while it's being read (presence, the countdown coming back): keep the reader's place.
  const place = again ? card.querySelector<HTMLElement>(".facts-text")?.scrollTop ?? 0 : 0;
  const since = pres.pendingConfirm === data.request_id ? P.waitingSince(pres) : null;
  // Swift's own card (send_email, calendar) shows what it will do (ADR-010 §4).
  const shown = data.artifact_id ? artifacts.get(data.artifact_id) : undefined;
  const email = shown?.kind === "email_draft";
  const approve = el("button", { class: "btn btn--warn btn--big", onclick: reply("approve") }, icon("check"), email ? "Send" : "Approve");
  showCard(
    el(
      "div",
      { class: "card-in" },
      el("div", { class: "band", role: "heading", "aria-level": "2" },
        icon("shield"), "Needs your OK", el("span", { class: "band-time", "aria-live": "off" })),
      threadLines(),
      el("p", { class: "confirm-title" }, data.title),
      since !== null ? el("p", { class: "confirm-since" }, `Held while you were away, since ${clock(since)}`) : null,
      confirmFacts(data, shown),
      el("p", { class: "voice-hint", "data-request": data.request_id }, ...voiceHint(data)),
      el(
        "div",
        { class: "confirm-actions" },
        el("button", { class: "btn btn--ghost btn--big", onclick: reply("reject") }, icon("x"), "Reject"),
        el("button", { class: "btn btn--ghost btn--big", title: "Type what to change (typing never approves)", onclick: () => changeByTyping() }, icon("edit"), "Change"),
        el("span", { class: "foot-gap" }),
        approve,
      ),
    ),
    `confirm${pres.away ? " card--away" : ""}`,
    "alert",
  );
  const box = card.querySelector<HTMLElement>(".facts-text");
  if (box && place) box.scrollTop = place;
  // Redrawn while the owner is away (a new draft version): it stays put aside.
  if (pres.held === data.request_id) card.classList.add("card--held");
  tickConfirm();
}

/** "Change" on a confirm card: the text box, where Enter sends a change; it never approves. */
function changeByTyping(): void {
  if (!typing) toggleTyping();
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
    if (stageNow() !== "confirm") setStage("confirm");
    renderConfirm(lastConfirm);  // the same card, with a fresh countdown and the "held" line
    // Locking the screen can leave the overlay hidden or behind other windows, and no hotkey
    // brought it forward this time (owner check 14, 2026-10-27).
    void invoke("reveal").catch(() => {});
  }
  drawCapsule();
  scheduleRegions();
}

/** After an answer: one line naming a conversation left unfinished. */
function onResumeOffer(data: Extract<Inbound, { type: "resume.offer" }>["data"]): void {
  if (stageNow() !== "result" && stageNow() !== "error") return;
  card.querySelector(".resume")?.remove();
  const line = el("p", { class: "voice-hint resume", "data-phase": "hint" }, icon("pause"), `Unfinished: ${data.title}. It's with what needs you.`);
  const foot = card.querySelector(".card-foot");
  if (foot) foot.before(line);
  else (card.firstElementChild ?? card).append(line);
  scheduleRegions();
}

/** The voice line on a confirm card: approving by voice takes push-to-talk (or Swift's name). */
function voiceHint(_data: unknown): (Node | string)[] {
  return [icon("mic"), "Or hold ", pttKeys(), " and say “approve”, “reject”, or what to change."];
}

/** The band's countdown and the bar: running, or stopped while the owner is away. */
function tickConfirm(): void {
  const node = card.querySelector<HTMLElement>(".band-time");
  if (!node || stageNow() !== "confirm") return;
  const left = P.confirmLeftMs(pres, Date.now());
  const bar = card.querySelector<HTMLElement>(":scope > .timebar");
  if (!left) {
    node.textContent = "";
    if (bar) bar.hidden = true;
    return;
  }
  node.textContent = left.paused ? "Paused · you're away" : countdownText(left.ms);
  card.classList.toggle("card--away", left.paused);
  if (bar) {
    bar.hidden = false;
    if (!bar.dataset.started || left.paused !== (bar.dataset.paused === "1")) {
      // (Re)start the drain from what is left; stopped, it holds.
      bar.dataset.started = "1";
      bar.dataset.paused = left.paused ? "1" : "0";
      bar.style.animation = "none";
      void bar.offsetWidth;
      bar.style.animation = "";
      card.style.setProperty("--fade-ms", `${left.ms}ms`);
      bar.classList.toggle("timebar--paused", left.paused);
    }
  }
}

// The owner is answering the confirm card by voice: show it on the card, not on the capsule.
function renderConfirmVoice(data: Extract<Inbound, { type: "confirm.voice" }>["data"]): void {
  const hint = card.querySelector<HTMLElement>(".voice-hint[data-request]");
  if (stageNow() !== "confirm" || !hint || hint.dataset.request !== data.request_id) return;
  hint.dataset.phase = data.phase;
  if (data.phase === "listening") hint.replaceChildren(icon("mic"), "Listening…");
  else if (data.phase === "transcribing") hint.textContent = "Transcribing…";
  else if (data.phase === "hint") hint.textContent = data.text;
  // A voice approval Swift held back (noise, or not sure what it heard): it needs one more.
  else if (data.phase === "again") hint.replaceChildren(icon("alert"), data.text);
  else hint.replaceChildren(...voiceHint(lastConfirm));
}

// ---- answers ---------------------------------------------------------------------------------

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

/** Paragraphs and lists with their marks, as elements (text only, never HTML). */
function renderBlocks(text: string): HTMLElement[] {
  const runs = (rs: A.Run[]): Node[] =>
    rs.map((r) => (r.marks.includes("b") ? el("strong", {}, r.text) : r.marks.includes("i") ? el("em", {}, r.text) : r.marks.includes("code") ? el("code", {}, r.text) : document.createTextNode(r.text)));
  return A.blocks(text).map((b) => (b.kind === "p" ? el("p", {}, ...runs(b.runs)) : el("ul", {}, ...b.items.map((i) => el("li", {}, ...runs(i))))));
}

/** ``full``: every row, for an answer opened with "Read more" (otherwise the first six). */
function renderDetails(details: ResultDetails | null | undefined, full = false): HTMLElement | null {
  if (!details) return null;
  const shown = full ? Infinity : 6;
  switch (details.kind) {
    case "text":
      return el("div", {}, ...renderBlocks(details.text));
    case "list": {
      const more = details.items.length - shown;
      return el(
        "div",
        {},
        el("ul", {}, ...details.items.slice(0, shown).map((item) => el("li", {}, item))),
        more > 0 ? el("p", { class: "answer-more" }, `and ${more} more (Read more shows them)`) : null,
      );
    }
    case "table": {
      const more = details.rows.length - shown;
      return el(
        "div",
        {},
        el(
          "table",
          { class: "answer-table" },
          el("thead", {}, el("tr", {}, ...details.columns.map((c) => el("th", { scope: "col" }, c)))),
          el("tbody", {}, ...details.rows.slice(0, shown).map((row) => el("tr", {}, ...row.map((c) => el("td", {}, c))))),
        ),
        more > 0 ? el("p", { class: "answer-more" }, `and ${more} more rows (Read more shows them)`) : null,
      );
    }
  }
}

function copyButton(text: string): HTMLElement {
  const button = el("button", { class: "btn btn--ghost", title: "Copy the answer" }, icon("copy"), "Copy");
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

/** Stopped / Not done: one row, then gone. */
function renderRowCard(glyph: string, word: string, desc: string, runId?: string, threadId?: string, summary?: string): void {
  if (!presentAnswer("result", ROW_FADE_MS, runId, threadId, summary)) return;
  showCard(
    el("div", { class: "card-in row-line", onclick: dismissUnlessControl },
      icon(glyph),
      el("span", { class: "row-word" }, word),
      el("span", { class: "row-desc", title: desc }, desc),
      el("button", { class: "icon-btn", "aria-label": "Close", title: "Close", onclick: (ev: Event) => { ev.stopPropagation(); dismiss(); } }, icon("x"))),
    "result card--row",
  );
  showDeadline();
}

// The result on screen, for the question card it may become.
let lastResult: Extract<Inbound, { type: "result" }>["data"] | null = null;

function renderResult(data: Extract<Inbound, { type: "result" }>["data"]): void {
  question = null;
  if (data.status === "cancelled") {
    // Esc or "stop": the owner knows what happened, so just acknowledge it.
    renderRowCard("stop", "Stopped", request ? `“${request}”` : data.summary || "The request was stopped.", data.run_id, data.thread_id);
    return;
  }
  if (data.status === "rejected") {
    renderRowCard("x", "Not done", data.summary, data.run_id, data.thread_id, `Not approved: ${clipLine(data.summary)}`);
    return;
  }
  if (data.run_id.startsWith("due-")) {
    renderDue(data);
    return;
  }
  lastResult = data;
  // What the run finished showing (the calendar's table, ADR-015 §6) is part of the answer.
  const finished = finishedArtifacts();
  const extra = [detailsText(data.details), ...finished.map((a) => `${a.title}\n${detailsText(a.data)}`)].filter(Boolean).join("\n\n");
  const copyable = [data.summary, extra].filter(Boolean).join("\n\n");
  const readable = finished.length ? finished[finished.length - 1] : null;
  const fuller = data.details ?? readable?.data ?? null;
  // A long answer opens in place, on this card (owner checks 2026-10-28: a separate reader
  // window wasn't easy to read). Open, it stays until "Read less", Esc or a click on it.
  const long = Panes.needsReader(data.summary, fuller) || finished.length > 1;
  const shape = A.shape(data.summary, fuller, long);
  if (!presentAnswer("result", A.readingMs(copyable), data.run_id, data.thread_id, clipLine(data.summary))) return;
  setExpanded(false);
  const body = el("div", { class: shape === "line" ? "answer answer--line" : `answer${long ? " answer--long" : ""}`, tabindex: long ? "0" : "-1" });
  body.addEventListener("scroll", () => noteScroll(), { passive: true });
  const drawBody = (): void => {
    const parts: (HTMLElement | null)[] = shape === "line"
      ? renderBlocks(data.summary)
      : [
          ...renderBlocks(data.summary),
          renderDetails(data.details, expanded),
          ...finished.flatMap((a) => [el("p", { class: "section-title" }, a.title), renderDetails(a.data, expanded)]),
        ];
    body.replaceChildren(...parts.filter((n): n is HTMLElement => n !== null));
    scheduleRegions();
  };
  const foot = el("footer", { class: "card-foot" });
  const showBtn = artifacts.size > finished.length
    ? el("button", { class: "btn btn--ghost", onclick: (ev: Event) => { ev.stopPropagation(); askView("show"); } }, icon("external"), "Show")
    : null;
  const drawFoot = (): void => {
    if (long) {
      foot.replaceChildren(
        el("button", { class: "link", "aria-expanded": String(expanded), onclick: (ev: Event) => {
          ev.stopPropagation();
          setExpanded(!expanded);
          body.classList.toggle("answer--open", expanded);
          card.classList.toggle("card--open", expanded);
          drawBody();
          drawFoot();
        } }, expanded ? "Read less" : "Read more", icon(expanded ? "collapse" : "expand")),
        el("span", { class: "hint foot-gap" }, expanded ? "Stays while open" : `· ${A.minutesToRead(copyable)}`),
        ...(showBtn ? [showBtn] : []),
        copyButton(copyable),
      );
    } else {
      foot.replaceChildren(el("span", { class: "byline" }, byline(data.agent)), ...(showBtn ? [showBtn] : []), copyButton(copyable));
    }
  };
  drawBody();
  drawFoot();
  showCard(
    el(
      "div",
      { class: "card-in", onclick: dismissUnlessControl },
      headRow(),
      threadLines(),
      data.note ? el("p", { class: "answer-note" }, data.note) : null,
      body,
      foot,
    ),
    "result",
  );
  showDeadline();
}

/** Swift's question (ADR-017): asking while it speaks, then waiting for the answer for the
 * backend's whole reply window. Never "Done"; unanswered, the backend puts it in the stack. */
function renderQuestion(): void {
  if (!question || stageNow() !== "result") return;
  const q = question;
  const thread = q.data.thread_id ?? pres.threadId;
  const left = pres.followupUntil ? Math.max(0, pres.followupUntil - Date.now()) : 0;
  const asking = speaking;
  const later = (): void => {
    if (thread) stackAction(`parked:${thread}`, "skip");
    question = null;
    dismiss();
  };
  const cancel = (): void => {
    if (thread) stackAction(`parked:${thread}`, "end");
    question = null;
    dismiss();
  };
  const pill = asking
    ? el("div", { class: "q-pill q-pill--speaking" }, el("span", { class: "wave", "aria-hidden": "true" }, ...Array.from({ length: 6 }, () => el("i", {}))),
        el("span", { class: "q-pill-text" }, "Speaking… I'll listen when I'm done"))
    : el("div", { class: "q-pill" }, el("span", { class: "orb", "aria-hidden": "true" }),
        el("span", { class: "q-pill-text" }, "Listening for your answer"),
        el("span", { class: "elapsed" }, `0:${String(Math.ceil(left / 1000)).padStart(2, "0")}`),
        left ? el("span", { class: "timebar", style: `--fade-ms:${left}ms` }) : null);
  const about = q.words ? `about “${clipLine(q.words, 48)}”` : "";
  showCard(
    el(
      "div",
      { class: "card-in" },
      el("div", { class: "q-tags" },
        el("span", { class: asking ? "tag" : "tag tag--fill" }, asking ? "Swift is asking" : "Waiting for you"),
        el("span", { class: "q-about" }, about)),
      el("p", { class: "q-title" }, A.plainText(q.data.summary)),
      pill,
      el("footer", { class: "card-foot" },
        typeSpec ? el("span", { class: "hint foot-gap" }, "Or type", keys(typeSpec)) : el("span", { class: "foot-gap" }),
        el("button", { class: "btn btn--ghost", onclick: later }, "Answer later"),
        el("button", { class: "btn btn--ghost", onclick: cancel }, "Cancel request")),
    ),
    `result card--question${asking ? "" : " card--waiting"}`,
  );
  showDeadline();
  card.querySelector<HTMLElement>(":scope > .timebar")!.hidden = true;  // the pill has the time
}

/** Swift's question while a request runs (ADR-016 §5.1): said, then waiting for the answer, said,
 * typed or clicked. The backend closes it; unanswered, it goes to the stack with its conversation. */
function renderAsk(a: Q.Ask): void {
  const asking = speaking || a.phase === "asking";
  const left = Q.askLeft(a, Date.now());
  const reply = (text: string) => (ev: Event): void => {
    ev.stopPropagation();
    client.send({ type: "ask.reply", data: { ask_id: a.id, text } });
  };
  const pill = asking
    ? el("div", { class: "q-pill q-pill--speaking" }, el("span", { class: "wave", "aria-hidden": "true" }, ...Array.from({ length: 6 }, () => el("i", {}))),
        el("span", { class: "q-pill-text" }, Q.askPill(a, speaking)))
    : el("div", { class: "q-pill" }, el("span", { class: "orb", "aria-hidden": "true" }),
        el("span", { class: "q-pill-text", "aria-live": "polite" }, Q.askPill(a, speaking)),
        left ? el("span", { class: "elapsed" }, `0:${String(left).padStart(2, "0")}`) : null,
        left ? el("span", { class: "timebar", style: `--fade-ms:${left * 1000}ms` }) : null);
  // Swift's own question says what it's about; ``request`` may be another request's words.
  const about = request && !Q.ownQuestion(a) ? `about “${clipLine(request, 48)}”` : "";
  const buttons = Q.askButtons(a).map((o) => el("button", { class: "btn", onclick: reply(o) }, o));
  showCard(
    el(
      "div",
      { class: "card-in" },
      el("div", { class: "q-tags" },
        el("span", { class: asking ? "tag" : "tag tag--fill" }, asking ? "Swift is asking" : "Waiting for you"),
        el("span", { class: "q-about" }, about)),
      el("p", { class: "q-title" }, a.question),
      a.note ? el("p", { class: "q-note" }, a.note) : null,
      pill,
      buttons.length ? el("div", { class: "q-options" }, ...buttons) : null,
      el("footer", { class: "card-foot" },
        typeSpec && !Q.ownQuestion(a) ? el("span", { class: "hint foot-gap" }, "Or type", keys(typeSpec)) : el("span", { class: "foot-gap" }),
        Q.ownQuestion(a) ? null : el("button", { class: "btn btn--ghost", onclick: (ev: Event) => {
          ev.stopPropagation();
          client.send({ type: "run.stop", data: { run_id: a.runId } });
        } }, "Stop request")),
    ),
    `working card--question${asking ? "" : " card--waiting"}`,
  );
  const bar = card.querySelector<HTMLElement>(":scope > .timebar");
  if (bar) bar.hidden = true;  // the pill has the time
}

function onAskMessage(data: Q.AskData): void {
  asked = Q.onAsk(asked, data, Date.now());
  if (stageNow() === "working") renderWorking();
}

/** A timer, alarm or reminder came due: it stays until Done (ADR-017). */
function renderDue(data: Extract<Inbound, { type: "result" }>["data"]): void {
  if (!presentAnswer("result", null, data.run_id, data.thread_id, clipLine(data.summary))) return;
  // Drawn: only now does it leave the schedule; dropped, the backend shows it again later (O-08).
  client.send({ type: "due.shown", data: { run_id: data.run_id } });
  const kind = data.run_id.split("-")[1];
  const label = { timer: "Timer", alarm: "Alarm", reminder: "Reminder", away: "While you were away" }[kind] ?? "Reminder";
  // The label says what it is; the title is the rest ("Reminder: call mum." → "Call mum.").
  const rest = data.summary.replace(/^(While you were away|Reminder): /, "");
  const title = rest.charAt(0).toUpperCase() + rest.slice(1);
  showCard(
    el("div", { class: "card-in due" },
      el("span", { class: "due-icon" }, icon(kind === "timer" ? "timer" : "bell")),
      el("span", { class: "due-text" }, el("p", { class: "due-label" }, label), el("p", { class: "due-title" }, title)),
      el("button", { class: "btn btn--primary btn--big", onclick: (ev: Event) => { ev.stopPropagation(); dismiss(); } }, "Done")),
    "result card--due",
    "alert",
  );
  showDeadline();
}

/** Tables, lists and text the run finished showing (the calendar's "Your calendar: …"). */
type Finished = Extract<Artifact, { kind: "text" | "list" | "table" }>;
function finishedArtifacts(): Finished[] {
  return [...artifacts.values()].filter((a): a is Finished => (a.kind === "table" || a.kind === "list" || a.kind === "text") && a.phase === "done");
}

/** One line of an answer, for the thread's history. */
function clipLine(text: string, max = 90): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length <= max ? flat : `${flat.slice(0, max - 1).trimEnd()}…`;
}

/** Clicking a card dismisses it, except on its controls, open text, or after dragging it. */
function dismissUnlessControl(ev: Event): void {
  const e = ev as MouseEvent;
  if ((ev.target as HTMLElement).closest("button, a, .detail, details, .answer--open, .draft-body, .mail-body")) return;
  if (pressAt && Math.abs(e.screenX - pressAt.x) + Math.abs(e.screenY - pressAt.y) > 4) return;  // it was a drag
  if (window.getSelection()?.toString()) return;  // selecting text
  dismiss();
}

// Shown when Swift is launched again while already running (single-instance plugin).
function renderAlreadyRunning(): void {
  if (!presentAnswer("notice", READY_FADE_MS + 1500)) return; // never over a request
  renderNotice("ok", "Swift is already running", el("span", {}, "Hold ", pttKeys(), " and speak. Its icon is in the system tray."));
}

function renderReady(): void {
  if (card.classList.contains("card--in") || !presentAnswer("notice", READY_FADE_MS)) return;
  renderNotice("ok", "Swift is ready", el("span", {}, "Hold ", pttKeys(), " and speak."));
}

/** One of Swift's own notices (ready, already running): a check, a title, a line. */
function renderNotice(_kind: "ok", title: string, line: HTMLElement): void {
  showCard(
    el("div", { class: "card-in", onclick: dismissUnlessControl },
      el("div", { class: "fail" }, el("span", { class: "ok-dot" }, icon("check")),
        el("div", {}, el("p", { class: "fail-title" }, title), el("p", { class: "fail-why" }, line))),
    ),
    "result",
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
  // Restart Swift (the engine stopped: audit 2026-10, B-04).
  restart?: boolean;
  agent?: Agent | null;
  // Stays until dismissed: Swift can't work until it's fixed.
  sticky?: boolean;
  glyph?: string;
  runId?: string;
  threadId?: string;
};

function renderProblem(p: Problem): void {
  const info = p.severity === "info";
  if (!presentAnswer("error", p.sticky ? null : info ? INFO_FADE_MS : p.retry ? RETRY_FADE_MS : ERROR_FADE_MS, p.runId, p.threadId, clipLine(p.title))) return;
  let open = false;
  const detail = p.detail ? el("pre", { class: "detail", hidden: true }, p.detail) : null;
  const toggle = detail
    ? el("button", { class: "link link--quiet", "aria-expanded": "false", onclick: (ev: Event) => {
        ev.stopPropagation();
        open = !open;
        detail.hidden = !open;
        toggle!.setAttribute("aria-expanded", String(open));
        toggle!.textContent = open ? "Hide details" : "Details";
        scheduleRegions();
      } }, "Details")
    : null;
  const actions: HTMLElement[] = [];
  if (p.logs) actions.push(el("button", { class: "btn btn--ghost", onclick: () => void invoke("open_logs") }, "Open logs"));
  if (p.restart) {
    actions.push(el("button", { class: "btn btn--primary", onclick: (ev: Event) => {
      (ev.currentTarget as HTMLButtonElement).disabled = true;
      restartSwift();
    } }, "Restart Swift"));
  }
  if (p.retry) {
    actions.push(
      el("button", { class: "btn btn--primary", onclick: (ev: Event) => {
        (ev.currentTarget as HTMLButtonElement).disabled = true;
        if (!client.send({ type: "retry", data: {} })) renderConnection(true);
      } }, "Try again"),
    );
  }
  const bang = p.glyph === "spin"
    ? el("span", { class: "spinner", "aria-hidden": "true" })
    : el("span", { class: info ? "bang bang--info" : "bang", "aria-hidden": "true" }, info ? "i" : "!");
  showCard(
    el(
      "div",
      { class: "card-in", onclick: dismissUnlessControl },
      p.runId || p.threadId ? headRow() : null,
      el("div", { class: "fail" }, bang,
        el("div", {},
          el("p", { class: "fail-title" }, p.title),
          el("p", { class: "fail-why" }, withKeys(p.message, pttSpec)),
          p.hint ? el("p", { class: "fail-why" }, withKeys(p.hint, pttSpec)) : null)),
      detail,
      toggle || actions.length || p.agent
        ? el(
            "footer",
            { class: "card-foot" },
            toggle ?? (p.agent ? el("span", { class: "byline" }, byline(p.agent)) : null),
            el("span", { class: "foot-gap" }),
            ...actions,
          )
        : null,
    ),
    info ? "error card--info" : "error",
    info ? "status" : "alert",
  );
  if (!(p.runId || p.threadId)) {
    // No request to name: the close button sits in the corner.
    card.firstElementChild?.prepend(el("button", { class: "icon-btn", style: "position:absolute;top:8px;right:8px", "aria-label": "Close", title: "Close", onclick: (ev: Event) => { ev.stopPropagation(); dismiss(); } }, icon("x")));
  }
  showDeadline();
}

function renderError(data: ErrorData): void {
  renderProblem({
    title: data.title || "Something went wrong",
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
    renderProblem({ title: "Reconnecting to Swift…", message: "Your next request will work once it's back.", severity: "info", glyph: "spin", sticky: true });
    return;
  }
  renderProblem({ ...describeBackendProblem(status.problem), sticky: true, logs: true });
}

/** Restart Swift (the tray, or a stopped engine's card): Rust ends the old engine and starts a new
 * one; this overlay reconnects by itself, and the card goes once it's back. */
function restartSwift(): void {
  void invoke("restart_backend").catch((err) => onRestartFailed(String(err)));
}

function onRestartFailed(problem: string): void {
  renderProblem({ title: "Swift couldn't restart", message: problem, hint: "Quit Swift from the tray icon and start it again.", logs: true, sticky: true });
}

// From either Restart Swift (the native tray menu's too): say so until the new engine is connected.
void listen("backend-restarting", () => {
  renderProblem({ title: "Restarting Swift…", message: "It'll be ready in a few seconds.", severity: "info", glyph: "spin", sticky: true });
});
void listen<string>("backend-restart-failed", ({ payload }) => onRestartFailed(payload));

// ---- hover, drag, Read more and scrolling hold an answer (the presenter keeps the time) -------

/** "Read more" holds the answer while it's open; "Read less" gives back the time it had left. */
function setExpanded(open: boolean): void {
  if (open === expanded) return;
  expanded = open;
  setHold(!open);
  drawRows();  // the deck folds to one edge, so a long answer isn't squeezed (ADR-018)
}

// Scrolling a long answer holds it too, until a moment after the last scroll.
let scrollHold = 0;
let scrolling = false;
function noteScroll(): void {
  scrolling = true;
  setHold();
  window.clearTimeout(scrollHold);
  scrollHold = window.setTimeout(() => { scrolling = false; setHold(); }, 400);
}

function setHold(restore = false): void {
  const selecting = !!window.getSelection()?.toString() && card.contains(window.getSelection()?.anchorNode ?? null);
  pres = P.onHold(pres, hovering || dragging || expanded || scrolling || selecting, Date.now(), restore);
  showDeadline();
}
document.addEventListener("selectionchange", () => setHold());

function setHover(inside: boolean): void {
  hovering = inside;
  if (!inside) card.classList.remove("card--hover");
  setHold();
}

// The pointer on the card itself, not on an edge behind it: a working card that shrank opens only
// then, or an edge would move out from under the pointer. The window sees pointer moves only while
// the pointer is over a hit region; its enter and leave events can be stale, so these are moves.
card.addEventListener("pointermove", () => {
  card.classList.add("card--hover");
  lastLookAt = Date.now();
  if (quiet) {
    quiet = false;
    if (stageNow() === "working") renderWorking();
  }
}, { passive: true });
rowsEl.addEventListener("pointermove", () => card.classList.remove("card--hover"), { passive: true });

// ---- the one clock: answers fade and the reply window counts down only here ---------

// The stack's rings (time left before an item leaves) move on by themselves: redraw them now and then.
window.setInterval(() => {
  if (!stack.items.some((i) => i.expires_ms)) return;
  void syncPanes();
  drawStackInline();
}, 15_000);

window.setInterval(() => {
  const r = P.tick(pres, Date.now());
  pres = r.p;
  if (r.hide) {
    question = null;
    setStage("idle");
  }
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
  const cardShown = card.classList.contains("card--in") && !card.classList.contains("card--held");
  // Outermost hit areas only: a nested one adds nothing. The capsule is one only with a button.
  const rects = Array.from(document.querySelectorAll<HTMLElement>("[data-hit]"))
    .filter((node) => !node.parentElement?.closest("[data-hit]"))
    .filter((node) => (node === card ? cardShown : true))
    .filter((node) => !node.closest("[hidden]"))
    .map((node) => {
      const r = node.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    })
    .filter((r) => r.w > 0 && r.h > 0);
  const key = JSON.stringify(rects);
  if (key === lastRegions) return;
  lastRegions = key;
  void invoke("set_hit_regions", { rects });
}

function scheduleRegions(): void {
  regionTimers.forEach((t) => window.clearTimeout(t));
  // Now, and again once what moved (160 ms for the card, 280 ms for an edge) has settled.
  regionTimers = [window.setTimeout(sendRegions, 0), window.setTimeout(sendRegions, 220), window.setTimeout(sendRegions, 320)];
  if (!card.classList.contains("card--in")) sendRegions();
}
new ResizeObserver(scheduleRegions).observe(card);
new ResizeObserver(scheduleRegions).observe(capsuleEl);

// ---- moving the overlay -----------------------------------------------------------

// Pressing a card anywhere but a control hands the drag to Rust, which follows the cursor; the
// card stays where it is dropped (a press without moving is a click).
card.addEventListener("pointerdown", (ev) => {
  const target = ev.target as HTMLElement;
  pressAt = { x: ev.screenX, y: ev.screenY };
  if (ev.button !== 0 || target.closest("button, a, input, .answer--open, .detail, .draft-body, .mail-body--full, .facts-text")) return;
  void invoke("begin_drag");
});

function setAnchor(anchor: string): void {
  stage.dataset.anchor = anchor;
  scheduleRegions();
}

// ---- once a second: elapsed time, stall note, confirm countdown -----------------

let sweepTick = 0;

window.setInterval(() => {
  if (stageNow() === "working") {
    const node = card.querySelector<HTMLElement>(".elapsed");
    if (node && Date.now() - runStarted > ELAPSED_AFTER_MS) node.textContent = elapsedText();
    if (isStalled(Date.now()) !== !!card.querySelector(".note")) renderWorking();
    // No news and nobody looking: shrink to the one line (ADR-015 §3.3, ADR-017: 12 s).
    if (!quiet && Panes.workingQuiet(Math.max(lastStepAt, runStarted, lastLookAt), Date.now(), hovering)) {
      quiet = true;
      renderWorking();
    }
    drawCapsule();
  } else if (stageNow() === "confirm") tickConfirm();
  if (pres.rows.length) drawRows();  // their elapsed time, and "Got it" settling
  // The stack's glow fades: that's in what's wanted.
  if (paneWindows && stack.items.length) void syncPanes();
  if (++sweepTick % 3 === 0) void sweepPanes();
  setLive(L.tick(live, Date.now(), liveHovered()));
  if (!paneWindows && L.openRuns(live).some((r) => !r.ended)) {
    for (const node of liveEl?.querySelectorAll<HTMLElement>(".live--running .elapsed") ?? []) {
      const r = L.find(live, node.closest<HTMLElement>("[data-run]")?.dataset.run ?? "");
      if (r) node.textContent = V.elapsed(r.startedMs);
    }
  }
  const shrunk = Panes.readerTick(reader, Date.now(), false);
  if (shrunk !== reader) {
    reader = shrunk;
    void syncPanes();
  }
}, 1000);

/** Inline live views the pointer is on (the harness); a pane window reports its own (live-touch). */
function liveHovered(): Set<string> {
  return new Set([...(liveEl?.querySelectorAll<HTMLElement>("[data-run]:hover") ?? [])].map((n) => n.dataset.run ?? ""));
}

// ---- Esc: only grabbed while Swift is active, speaking, or the stack is open -----------

async function syncEscape(): Promise<void> {
  const want = (ACTIVE.has(stageNow()) || speaking || stack.expanded) && !typing;
  if (want === escapeActive) return;
  escapeActive = want;
  try {
    await invoke("set_escape", { active: want });
  } catch (err) {
    console.warn("Esc hotkey:", err);
  }
}

/** Esc: Swift stops talking first, then the request stops, then the open stack folds up. */
function onEscape(): void {
  if (speaking) stopSpeaking();
  else if (ACTIVE.has(stageNow())) client.send({ type: "cancel", data: {} });
  else if (stack.expanded) collapseStack();
}

// ---- backend messages ----------------------------------------------------------

function onMessage(msg: Inbound): void {
  if (wantsRaise(msg)) void invoke("raise").catch(() => {});  // on top again, where it is
  if (msg.type !== "level") recent.push(`${msg.type}${"state" in msg.data ? `:${msg.data.state}` : ""}`), recent.splice(0, recent.length - 30);
  switch (msg.type) {
    case "hello.ok":
      if (msg.data.instance && backendInstance && msg.data.instance !== backendInstance) forgetBackend();
      backendInstance = msg.data.instance ?? backendInstance;
      debugEnabled = msg.data.debug;
      if (msg.data.hotkeys.push_to_talk) pttSpec = msg.data.hotkeys.push_to_talk;
      typeSpec = msg.data.hotkeys.type ?? "";
      void registerHotkeys(msg.data.hotkeys);
      void invoke("set_status", { text: `Swift: ready. Hold ${pttText()} to talk.` }).catch(() => {});
      break;
    case "state":
      if (msg.data.agent !== undefined) agent = msg.data.agent;
      setStage(msg.data.state, msg.data.run_id ?? null, msg.data.thread_id ?? null);
      if (msg.data.run_id && request) setLive(L.name(live, msg.data.run_id, request, request));
      break;
    case "level":
      orb.setLevel(msg.data.rms);
      noteLevel(msg.data.rms);
      break;
    case "transcript":
      transcriptText = msg.data.text;
      if (msg.data.text && quietNow) quietNow = false;
      if (msg.data.final) {
        request = msg.data.text;
        typed = !!msg.data.typed;
      }
      drawCapsule();
      break;
    case "step":
      steps = [...steps, msg.data.text].slice(-MAX_STEPS);
      lastStepAt = Date.now();
      quiet = false;
      current = { activity: msg.data.activity, agent: msg.data.agent ?? agent, subagent: msg.data.subagent ?? false, app: msg.data.app };
      if (stageNow() === "working") renderWorking();
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
      if (asked?.runId === msg.data.run_id) asked = null;  // its request ended: the question with it
      setLive(L.ended(live, msg.data.run_id, msg.data.status, msg.data.summary, msg.data.details ?? null, Date.now()));
      renderResult(msg.data);
      break;
    case "error":
      if (msg.data.code === "bad_message") {
        // A frame the backend couldn't read (version skew after a reload): never the owner's card (O-05).
        console.warn("backend refused a frame:", msg.data.message);
        break;
      }
      if (pres.runId) setLive(L.ended(live, pres.runId, "error", msg.data.title ?? msg.data.message, null, Date.now()));
      renderError(msg.data);
      break;
    case "live":
      setLive(L.onItem(live, msg.data.run_id, msg.data, Date.now()));
      break;
    case "watch":
      if (msg.data.open) setLive(L.watch(live, msg.data.run_id, msg.data.title ?? "", msg.data.words ?? "", Date.now()));
      else setLive(L.close(live, msg.data.run_id));
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
    case "stack":
      onStackMessage(msg.data.items);
      break;
    case "heard":
      onHeard(msg.data);
      break;
    case "speech":
      onSpeech(msg.data.speaking);
      break;
    case "ask":
      onAskMessage(msg.data);
      break;
  }
}

/** Swift started or stopped talking: the capsule's Speaking and Stop, and the question card. */
function onSpeech(now: boolean): void {
  if (speaking === now) return;
  speaking = now;
  drawCapsule();
  void syncEscape();
  if (question) renderQuestion();
  if (asked && stageNow() === "working") renderWorking();
}

/** Swift heard its name or the hotkey: the capsule says so at once, before any transcription. */
function onHeard(data: Extract<Inbound, { type: "heard" }>["data"]): void {
  const arrived = performance.now();
  heardNow = H.heard(Date.now(), data.source, data.text);
  drawCapsule();
  // The design asks for the heard capsule within 100 ms of the wake word: log how long drawing took.
  if (debugEnabled) requestAnimationFrame(() => console.debug(`[overlay] heard drawn ${Math.round(performance.now() - arrived)} ms after the message`));
  window.clearTimeout(heardTimer);
  heardTimer = window.setTimeout(() => { heardNow = null; drawCapsule(); }, H.HEARD_MS);
}

/** While listening: flag a mic that hears nothing for 4 s, so silence isn't mistaken for "Swift is broken". */
function noteLevel(rms: number): void {
  if (stageNow() !== "listening") return;
  loudest = Math.max(loudest, rms);
  const quietThen = rms < C.QUIET_LEVEL && loudest < C.QUIET_LEVEL && performance.now() - listenStarted > C.QUIET_MS;
  const next = rms >= C.QUIET_LEVEL ? false : quietThen || quietNow;
  if (next !== quietNow) {
    quietNow = next;
    drawCapsule();
  }
}

function onStatus(status: ConnectionStatus): void {
  const was = connection.phase;
  connection = status;
  stage.dataset.backend = status.phase;
  refreshTray();
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
  } else if (status.phase === "lost" && ACTIVE.has(stageNow())) {
    // The run it was doing is gone with the connection.
    orb.stop();
    speaking = false;
    renderConnection(true);
  }
}

type HotkeyProblem = { name: string; spec: string; reason: "invalid" | "in_use"; detail: string };

async function registerHotkeys(hotkeys: Record<string, string>): Promise<void> {
  const wanted: Record<string, string> = {};
  if (hotkeys.push_to_talk) wanted.push_to_talk = hotkeys.push_to_talk;
  if (debugEnabled && hotkeys.debug) wanted.debug = hotkeys.debug;
  if (hotkeys.type) wanted.type = hotkeys.type;
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
  const typeKey = problems.find((p) => p.name === "type");
  if (typeKey) typeSpec = "";
  if (typeKey && !ptt) {
    renderProblem({
      title: "The typing shortcut isn't working",
      message: typeKey.reason === "in_use" ? `${hotkeyParts(typeKey.spec).join("+")} is already used by another app.` : `“${typeKey.spec}” isn't a shortcut Swift understands.`,
      hint: "Pick another one for hotkeys.type in config.yaml, or use “Type to Swift” in the tray menu.",
      detail: typeKey.detail,
      severity: "info",
    });
  }
  if (readyTimes === null) {
    // Startup time, measured once per launch: process start to "usable".
    const t = await invoke<{ startup_ms: number; backend_ms: number | null }>("overlay_ready");
    readyTimes = { startup_ms: Number(t.startup_ms), backend_ms: t.backend_ms === null ? null : Number(t.backend_ms) };
  }
  // Every connection, not once per page: the backend then tells this overlay everything on screen (O-01, O-02).
  client.send({ type: "ready", data: readyTimes });
}

/** A different backend answered (Swift restarted): what the last one put on screen is gone. The new
 * one sends what is on screen now, after ``ready``. */
function forgetBackend(): void {
  asked = null;
  onMessage({ type: "stack", data: { items: [] } });
  onMessage({ type: "runs", data: { focus: null, rows: [], waiting: 0 } });
  onMessage({ type: "state", data: { state: "idle" } });
}

// ---- hotkeys from Rust -----------------------------------------------------------

void listen<{ name: string; state: "down" | "up" }>("hotkey", ({ payload }) => {
  if (payload.name === "escape" && payload.state === "down") {
    onEscape();
  } else if (payload.name === "debug" && payload.state === "down" && debugEnabled && !ACTIVE.has(stageNow())) {
    // Ignored while busy (the backend would ignore it too), so the cycle doesn't skip a scenario.
    const scenario: Scenario = SCENARIOS[scenarioIndex++ % SCENARIOS.length];
    client.send({ type: "debug.run", data: { scenario } });
  } else if (payload.name === "type" && payload.state === "down") {
    toggleTyping();
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
  const ended = dragging && !payload;
  dragging = payload;
  setHold(ended);
});

void invoke<{ anchor: string }>("get_placement").then((p) => setAnchor(p.anchor)).catch(() => {});
drawCapsule();
client.start();

// Dev harness: the presenter and the capsule's inputs, for checks by eye (never used by the app).
(window as unknown as Record<string, unknown>).__overlay = {
  get pres() { return pres; },
  get presence() { return capsuleEl.dataset.p; },
  get speaking() { return speaking; },
};

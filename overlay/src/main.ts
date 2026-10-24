// Overlay renderer. The backend owns the state machine; this file draws it,
// forwards hotkeys, manages Esc registration, fade timers and click-through regions.
// Failure cards, connection status, placement and dragging: ADR-009.

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { activityLabel, byline, handoffLabel } from "./agents";
import { el, hotkeyParts, icon, keys, withKeys } from "./dom";
import { BackendClient, type ConnectionStatus } from "./ipc";
import { Orb } from "./orb";
import { SCENARIOS, type Activity, type Agent, type ErrorData, type Inbound, type ResultDetails, type Scenario, type UiState } from "./protocol";

const INFO_FADE_MS = 5000;
const ERROR_FADE_MS = 12000;
const READY_FADE_MS = 4000;
const CANCELLED_FADE_MS = 2200;
const RESUME_FADE_MS = 2500;
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
const transcriptEl = document.getElementById("transcript")!;
const orb = new Orb(document.getElementById("orb")!);

let state: UiState = "idle";
let steps: string[] = [];
let request = "";
// The provider working on the current run, and what it last reported doing.
let agent: Agent | null = null;
let current: { activity?: Activity; agent: Agent | null; subagent: boolean } | null = null;
let runStarted = 0;
let lastStepAt = 0;
let nudgeUntil = 0;
let confirmDeadline = 0;
let compact = readPref("swift.compact") === "1";
let fadeTimer = 0;
let fadeMs = 0;
let hovering = false;
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

function setStage(next: UiState): void {
  state = next;
  stage.dataset.state = next;
  void syncEscape();

  if (next === "listening") orb.listen();
  else if (next === "transcribing") orb.settle();
  else orb.stop();

  if (next === "listening") {
    steps = [];
    request = "";
    agent = null;
    current = null;
    runStarted = 0;
    listenStarted = performance.now();
    loudest = 0;
    delete transcriptEl.dataset.quiet;
    transcriptEl.textContent = "";
    card.replaceChildren();
    card.className = "card";
    clearFade();
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
  clearFade();
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
  if (!ACTIVE.has(state)) setStage("idle");
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
  const list = el("ol", { class: "steps" });
  steps.forEach((text, i) => {
    const latest = i === steps.length - 1;
    list.append(el("li", { class: latest ? "step step--latest" : "step" }, el("span", { class: "step-dot" }), el("span", { class: "step-text" }, text)));
  });
  const title = current ? activityLabel(current.agent, current.activity, current.subagent) : handoffLabel(agent);
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
  const stalled = !compact && steps.length > 0 && busyAt - lastStepAt > STALL_MS;
  const nudging = busyAt < nudgeUntil;
  showCard(
    el(
      "div",
      {},
      head(el("span", { class: "spinner", "aria-hidden": "true" }), el("span", { class: "card-title card-title--live" }, title), [elapsed, toggle], false),
      compact ? null : request ? el("p", { class: "request" }, request) : null,
      compact ? null : steps.length ? list : el("p", { class: "muted" }, "Starting…"),
      stalled ? el("p", { class: "note note--soft" }, "Still working. Bigger requests can take a few minutes.") : null,
      nudging ? el("p", { class: "note note--warn", role: "alert" }, "Swift is still on this request. Stop it first to ask something new.") : null,
      el(
        "footer",
        { class: "card-foot" },
        el("span", { class: "hint" }, el("kbd", {}, "Esc"), " to stop"),
        el("button", { class: "btn btn--ghost btn--small", "data-hit": true, onclick: () => cancelRun() }, "Stop"),
      ),
    ),
    compact ? "working card--compact" : "working",
  );
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
  const timeout = data.timeout_s && data.timeout_s > 0 ? data.timeout_s * 1000 : 0;
  confirmDeadline = timeout ? Date.now() + timeout : 0;
  showCard(
    el(
      "div",
      { "data-hit": true },
      head(icon("shield"), "Approval needed", [data.tool ? el("span", { class: "chip" }, data.tool) : null], false),
      data.agent ? el("p", { class: "asker" }, `${data.agent.name} wants to:`) : null,
      el("p", { class: "confirm-title" }, data.title),
      data.detail ? el("p", { class: "muted detail-text" }, data.detail) : null,
      el("p", { class: "voice-hint", "data-request": data.request_id }, "Or hold ", pttKeys(), " and say “approve” or “reject”."),
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
  if (timeout) {
    card.style.setProperty("--fade-ms", `${timeout}ms`);
    card.classList.add("card--timed");
  }
  tickConfirm();
}

function tickConfirm(): void {
  const node = card.querySelector<HTMLElement>(".countdown");
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
  else hint.replaceChildren("Or hold ", pttKeys(), " and say “approve” or “reject”.");
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
        more > 0 ? el("p", { class: "more" }, `and ${more} more rows (Copy includes them)`) : null,
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
    showCard(el("div", { "data-hit": true, class: "hit-area", onclick: dismiss }, head(icon("stop"), "Cancelled")), "result card--neutral card--compact");
    startFade(CANCELLED_FADE_MS);
    return;
  }
  const variant = data.status === "done" ? "done" : "neutral";
  const glyph = data.status === "done" ? "check" : "x";
  const label = { done: "Done", rejected: "Not approved", error: "Failed" }[data.status];
  const extra = detailsText(data.details);
  const copyable = [data.summary, extra].filter(Boolean).join("\n\n");
  showCard(
    el(
      "div",
      { "data-hit": true, class: "hit-area", onclick: dismissUnlessControl },
      head(icon(glyph), label),
      data.note ? el("p", { class: "note" }, data.note) : null,
      el("p", { class: "summary" }, data.summary),
      renderDetails(data.details),
      el("footer", { class: "card-foot" }, el("span", { class: "byline" }, byline(data.agent)), data.status === "done" ? copyButton(copyable) : null),
    ),
    `result card--${variant}`,
  );
  startFade(readingMs(copyable));
}

/** Clicking a card dismisses it, except on its buttons and expandable details. */
function dismissUnlessControl(ev: Event): void {
  if ((ev.target as HTMLElement).closest("button, .detail, details")) return;
  dismiss();
}

// Shown when Swift is launched again while already running (single-instance plugin).
function renderAlreadyRunning(): void {
  if (ACTIVE.has(state)) return; // mid-interaction: don't cover the run
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
  startFade(READY_FADE_MS + 1500);
}

function renderReady(): void {
  if (ACTIVE.has(state) || card.classList.contains("card--in")) return;
  rest("result");
  showCard(
    el("div", { "data-hit": true, class: "hit-area", onclick: dismiss }, head(icon("check"), "Swift is ready"), el("p", { class: "summary" }, "Hold ", pttKeys(), " and speak.")),
    "result card--done card--compact-body",
  );
  startFade(READY_FADE_MS);
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
};

function renderProblem(p: Problem): void {
  const info = p.severity === "info";
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
  if (p.sticky) {
    clearFade();
    card.classList.add("card--sticky");
  } else startFade(info ? INFO_FADE_MS : ERROR_FADE_MS);
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

// ---- fade timers (paused while hovered) -------------------------------------

function clearFade(): void {
  window.clearTimeout(fadeTimer);
  fadeTimer = 0;
  fadeMs = 0;
}

function startFade(ms: number): void {
  clearFade();
  fadeMs = ms;
  card.style.setProperty("--fade-ms", `${ms}ms`);
  card.classList.remove("card--paused");
  if (!hovering) fadeTimer = window.setTimeout(() => setStage("idle"), ms);
}

function setHover(inside: boolean): void {
  hovering = inside;
  card.classList.toggle("card--hover", inside);
  if ((state !== "result" && state !== "error") || !fadeMs) return;
  if (inside) {
    window.clearTimeout(fadeTimer);
    card.classList.add("card--paused");
  } else {
    card.classList.remove("card--paused");
    fadeTimer = window.setTimeout(() => setStage("idle"), RESUME_FADE_MS);
  }
}

// ---- click-through regions ---------------------------------------------------

// Timers, not requestAnimationFrame: rAF can be throttled for a background
// webview, and a stale region would leave an invisible click-blocking area.
let regionTimers: number[] = [];

function sendRegions(): void {
  const visible = card.classList.contains("card--in");
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
    const stalled = Date.now() - lastStepAt > STALL_MS;
    if (stalled !== !!card.querySelector(".note--soft") && !compact) renderWorking();
    if (nudgeUntil && Date.now() >= nudgeUntil) {
      nudgeUntil = 0;
      renderWorking();
    }
  } else if (state === "confirm") tickConfirm();
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
  switch (msg.type) {
    case "hello.ok":
      debugEnabled = msg.data.debug;
      if (msg.data.hotkeys.push_to_talk) pttSpec = msg.data.hotkeys.push_to_talk;
      void registerHotkeys(msg.data.hotkeys);
      void invoke("set_status", { text: `Swift: ready. Hold ${pttText()} to talk.` }).catch(() => {});
      break;
    case "state":
      if (msg.data.agent !== undefined) agent = msg.data.agent;
      setStage(msg.data.state);
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
      current = { activity: msg.data.activity, agent: msg.data.agent ?? agent, subagent: msg.data.subagent ?? false };
      if (state === "working") renderWorking();
      break;
    case "confirm.request":
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
    else if (payload.state === "down" && state === "working") {
      // The backend ignores push-to-talk mid-run; say why nothing is listening.
      nudgeUntil = Date.now() + 3500;
      renderWorking();
    }
  }
});

void listen<{ inside: boolean }>("hover", ({ payload }) => setHover(payload.inside));
void listen("already-running", () => renderAlreadyRunning());
void listen<{ anchor: string }>("placement", ({ payload }) => setAnchor(payload.anchor));
void listen<boolean>("drag", ({ payload }) => {
  stage.dataset.dragging = String(payload);
  if (payload) window.clearTimeout(fadeTimer);
  else if (fadeMs && !hovering) fadeTimer = window.setTimeout(() => setStage("idle"), RESUME_FADE_MS);
});

void invoke<{ anchor: string }>("get_placement").then((p) => setAnchor(p.anchor)).catch(() => {});
client.start();

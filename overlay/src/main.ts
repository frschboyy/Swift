// Overlay renderer. The backend owns the state machine; this file draws it,
// forwards hotkeys, manages Esc registration, fade timers and click-through regions.

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { el, icon } from "./dom";
import { BackendClient, type ConnectionStatus } from "./ipc";
import { Orb } from "./orb";
import { SCENARIOS, type Inbound, type ResultDetails, type Scenario, type UiState } from "./protocol";

const RESULT_FADE_MS = 6000;
const ERROR_FADE_MS = 8000;
const RESUME_FADE_MS = 2500;
const MAX_STEPS = 5;
const ACTIVE: ReadonlySet<UiState> = new Set(["listening", "transcribing", "working", "confirm"]);

const stage = document.getElementById("stage")!;
const card = document.getElementById("card")!;
const transcriptEl = document.getElementById("transcript")!;
const orb = new Orb(document.getElementById("orb")!);

let state: UiState = "idle";
let steps: string[] = [];
let request = "";
let fadeTimer = 0;
let fadeMs = 0;
let hovering = false;
let escapeActive = false;
let debugEnabled = false;
let scenarioIndex = 0;
let lastRegions = "";

const client = new BackendClient(onMessage, onStatus);

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
    transcriptEl.textContent = "";
    card.replaceChildren();
    clearFade();
  }
  if (next === "transcribing") transcriptEl.dataset.pending = "true";
  if (next === "working") renderWorking();
  if (next === "idle") hideCard();
}

function showCard(node: HTMLElement, variant: string): void {
  card.className = `card card--${variant} card--in`;
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

function renderWorking(): void {
  const list = el("ol", { class: "steps" });
  steps.forEach((text, i) => {
    const latest = i === steps.length - 1;
    list.append(el("li", { class: latest ? "step step--latest" : "step" }, el("span", { class: "step-dot" }), el("span", { class: "step-text" }, text)));
  });
  showCard(
    el(
      "div",
      {},
      el("header", { class: "card-head" }, el("span", { class: "spinner" }), el("span", { class: "card-title" }, "Working"), el("kbd", { class: "hint" }, "Esc to cancel")),
      request ? el("p", { class: "request" }, request) : null,
      steps.length ? list : el("p", { class: "muted" }, "Starting…"),
    ),
    "working",
  );
}

function renderConfirm(data: Extract<Inbound, { type: "confirm.request" }>["data"]): void {
  const reply = (decision: "approve" | "reject") => () => {
    client.send({ type: "confirm.reply", data: { request_id: data.request_id, decision } });
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  };
  showCard(
    el(
      "div",
      {},
      el("header", { class: "card-head" }, icon("shield"), el("span", { class: "card-title" }, "Approval needed"), data.tool ? el("span", { class: "chip" }, data.tool) : null),
      el("p", { class: "confirm-title" }, data.title),
      data.detail ? el("p", { class: "muted" }, data.detail) : null,
      el(
        "div",
        { class: "actions" },
        el("button", { class: "btn btn--ghost", "data-hit": true, onclick: reply("reject") }, "Reject"),
        el("button", { class: "btn btn--primary", "data-hit": true, onclick: reply("approve") }, "Approve"),
      ),
    ),
    "confirm",
  );
}

function renderDetails(details: ResultDetails | null | undefined): HTMLElement | null {
  if (!details) return null;
  switch (details.kind) {
    case "text":
      return el("p", { class: "muted" }, details.text);
    case "list":
      return el("ul", { class: "result-list" }, ...details.items.slice(0, 6).map((item) => el("li", {}, item)));
    case "table":
      return el(
        "table",
        { class: "result-table" },
        el("thead", {}, el("tr", {}, ...details.columns.map((c) => el("th", {}, c)))),
        el("tbody", {}, ...details.rows.slice(0, 6).map((row) => el("tr", {}, ...row.map((c) => el("td", {}, c))))),
      );
  }
}

function renderResult(data: Extract<Inbound, { type: "result" }>["data"]): void {
  const variant = data.status === "done" ? "done" : "neutral";
  const glyph = data.status === "done" ? "check" : data.status === "cancelled" ? "stop" : "x";
  const label = { done: "Done", cancelled: "Cancelled", rejected: "Rejected", error: "Failed" }[data.status];
  showCard(
    el(
      "div",
      { "data-hit": true, class: "hit-area", onclick: () => setStage("idle") },
      el("header", { class: "card-head" }, icon(glyph), el("span", { class: "card-title" }, label)),
      el("p", { class: "summary" }, data.summary),
      renderDetails(data.details),
    ),
    `result card--${variant}`,
  );
  startFade(RESULT_FADE_MS);
}

function renderError(message: string, hint: string, fade = true): void {
  showCard(
    el(
      "div",
      { "data-hit": true, class: "hit-area", onclick: () => setStage("idle") },
      el("header", { class: "card-head" }, icon("alert"), el("span", { class: "card-title" }, "Something went wrong")),
      el("p", { class: "summary" }, message),
      hint ? el("p", { class: "muted" }, hint) : null,
    ),
    "error",
  );
  if (fade) startFade(ERROR_FADE_MS);
}

// ---- fade timers (paused while hovered) -------------------------------------

function clearFade(): void {
  window.clearTimeout(fadeTimer);
  fadeTimer = 0;
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
  if (state !== "result" && state !== "error") return;
  if (inside) {
    clearFade();
    card.classList.add("card--paused");
  } else if (fadeMs) {
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
  const rects = visible
    ? Array.from(document.querySelectorAll<HTMLElement>("[data-hit]")).map((node) => {
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
      void registerHotkeys(msg.data.hotkeys);
      break;
    case "state":
      setStage(msg.data.state);
      break;
    case "level":
      orb.setLevel(msg.data.rms);
      break;
    case "transcript":
      transcriptEl.textContent = msg.data.text;
      if (msg.data.final) {
        delete transcriptEl.dataset.pending;
        request = msg.data.text;
      }
      break;
    case "step":
      steps = [...steps, msg.data.text].slice(-MAX_STEPS);
      if (state === "working") renderWorking();
      break;
    case "confirm.request":
      renderConfirm(msg.data);
      break;
    case "result":
      renderResult(msg.data);
      break;
    case "error":
      renderError(msg.data.message, msg.data.hint);
      break;
  }
}

function onStatus(status: ConnectionStatus): void {
  if (status.connected) {
    if (stage.dataset.backend === "down") setStage("idle");
    stage.dataset.backend = "up";
    return;
  }
  stage.dataset.backend = "down";
  if (status.problem) {
    state = "error";
    stage.dataset.state = "error";
    renderError(`Swift's backend isn't available: ${status.problem}.`, "Quit Swift from the tray icon and start it again.", false);
  }
}

async function registerHotkeys(hotkeys: Record<string, string>): Promise<void> {
  // Milestone 1: only the debug key. Push-to-talk is registered from Milestone 2.
  const wanted: Record<string, string> = {};
  if (debugEnabled && hotkeys.debug) wanted.debug = hotkeys.debug;
  const problems = await invoke<string[]>("register_hotkeys", { hotkeys: wanted });
  if (problems.length) renderError(`Hotkey problem: ${problems.join("; ")}`, "Change the hotkey in config.yaml and restart Swift.");
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
    client.send({ type: "ptt", data: { state: payload.state } });
  }
});

void listen<{ inside: boolean }>("hover", ({ payload }) => setHover(payload.inside));

client.start();

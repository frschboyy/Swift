// A pane window (ADR-015 §3): another request as a chip, or a long answer in the reader.
//
// It draws only what the main window tells it (the ``pane`` event, for its own label) and sends
// clicks back (``pane-action``); the main window keeps the backend connection and the presenter.
// The whole window is the pane, so it is clickable all over: no click-through regions. Pressing
// anywhere but a button drags it (Rust follows the cursor and remembers where it went, per kind);
// a press that doesn't move is a click.
//
// ADR-015 §9, §10: the waiting stack (compressed; a double click expands it, a click anywhere
// else compresses it) and the text box, the one pane that takes the keyboard (Enter sends,
// Esc or clicking away closes it, keeping what was typed).
//
// ADR-017, the Capsule design: chips and the stack as views.ts draws them, the text box with
// "Typing can't approve" while a confirm card is open, and the tray menu (opened by a click on
// the tray icon, folded away by a click anywhere else). Dark or light follows Windows.
//
// ADR-017 §11: a request's live view. Its body keeps its place when an update redraws it, and
// follows the end of what is being written while the owner hasn't scrolled up. A source opens in
// the browser (Rust checks it is a web address); Stop, Show in Word and the answer go to the main window.

import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { el, icon, keys } from "./dom";
import type { LiveView } from "./live";
import type { PaneView, TrayView } from "./panes";
import type { ResultDetails } from "./protocol";
import { followTheme } from "./theme";
import * as V from "./views";

const label = getCurrentWindow().label;
const root = document.getElementById("stage")!;
let view: PaneView | null = null;
let lastTouch = 0;
// Two clicks this close make a double click (the press goes to Rust first, so no dblclick event).
const DOUBLE_MS = 450;
let lastClick = 0;
// Waiting for a click outside the expanded stack (or the tray menu).
let watching = false;
// The open stack's row the owner last pointed at.
let selected: string | null = null;

document.body.classList.add("pane-body");
root.dataset.pane = "true";
// The reader is at most 70 % of the screen's height; past that its body scrolls.
root.style.setProperty("--reader-max", `${Math.max(240, Math.round(screen.availHeight * 0.7) - 64)}px`);
root.style.setProperty("--live-max", `${Math.max(200, Math.min(380, Math.round(screen.availHeight * 0.7) - 200))}px`);
root.replaceChildren();
followTheme(root, { invoke: (cmd) => invoke(cmd), listen: (event, handler) => listen(event, handler) });

const act = (action: string, extra: Record<string, unknown> = {}): void => {
  void emitTo("overlay", "pane-action", { label, action, ...extra }).catch(() => {});
};

function details(d: ResultDetails | null): HTMLElement | null {
  if (!d) return null;
  switch (d.kind) {
    case "text":
      return el("p", { class: "summary" }, d.text);
    case "list":
      return el("ul", { class: "result-list" }, ...d.items.map((i) => el("li", {}, i)));
    case "table":
      return el(
        "table",
        { class: "answer-table" },
        el("thead", {}, el("tr", {}, ...d.columns.map((c) => el("th", { scope: "col" }, c)))),
        el("tbody", {}, ...d.rows.map((r) => el("tr", {}, ...r.map((c) => el("td", {}, c))))),
      );
  }
}

function plain(v: Extract<PaneView, { kind: "reader" }>): string {
  const d = v.details;
  const extra = !d ? "" : d.kind === "text" ? d.text : d.kind === "list" ? d.items.map((i) => `- ${i}`).join("\n")
    : [d.columns, ...d.rows].map((r) => r.join("\t")).join("\n");
  return [v.summary, extra].filter(Boolean).join("\n\n");
}

/** A press anywhere outside the expanded stack or the tray menu folds it away (the owner's design). */
function watchOutside(): void {
  if (watching) return;
  watching = true;
  const open = (): boolean => (view?.kind === "stack" && view.expanded) || view?.kind === "tray";
  void invoke<boolean>("watch_outside", { label })
    .then((outside) => {
      if (!outside || !open()) return;
      if (view?.kind === "tray") act("tray", { value: "close" });
      else act("stack-collapse");
    })
    .catch(() => {})
    .finally(() => {
      watching = false;
      if (open()) watchOutside();  // folded and opened again meanwhile
    });
}

/** The text box: Enter sends, Esc closes; what was typed is kept if it closes unsent. While a
 * confirm card is open it says typing can't approve (Enter sends a change). */
function drawType(v: Extract<PaneView, { kind: "type" }>): void {
  const notices = (): HTMLElement[] => ([
    v.confirm
      ? el("p", { class: "type-note type-note--warn", role: "note" }, icon("shield"),
          el("span", {}, el("b", {}, "Typing can't approve."), " Click Approve, or say “approve”."))
      : null,
    v.follows ? el("p", { class: "type-note type-note--follow" }, icon("info"), `Following up: ${v.follows}`) : null,
  ] as (HTMLElement | null)[]).filter((n): n is HTMLElement => n !== null);
  const hint = (): HTMLElement =>
    el("span", { class: "hint" }, ...(v.confirm ? [el("kbd", {}, "Enter"), "= Change"] : [el("kbd", {}, "Enter"), "sends ·", el("kbd", {}, "Esc"), "closes"]));
  const known = root.querySelector<HTMLInputElement>(".type-input");
  if (known) {
    // An update while typing must not wipe what's being typed: only the notice and the hint change.
    const box = root.querySelector<HTMLElement>(".type-box")!;
    box.querySelectorAll(".type-note").forEach((n) => n.remove());
    box.prepend(...notices());
    box.querySelector(".hint")?.replaceWith(hint());
    return;
  }
  const input = el("input", {
    class: "type-input", type: "text", value: v.draft, placeholder: "Type to Swift", "aria-label": "Type to Swift",
    autocomplete: "off", spellcheck: "true", maxlength: "2000",
  }) as HTMLInputElement;
  input.value = v.draft;
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      if (input.value.trim()) act("type-send", { text: input.value });
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      act("type-close", { text: input.value });
    }
  });
  root.replaceChildren(
    el(
      "section",
      { class: "type-box", role: "dialog", "aria-label": "Type to Swift" },
      ...notices(),
      el("div", { class: "type-row" }, icon("keyboard"), input, hint()),
    ),
  );
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

const ANCHORS = ["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"];
const anchorName = (a: string): string =>
  a.replace("top", "Top").replace("bottom", "Bottom").replace("-left", " left").replace("-center", " centre").replace("-right", " right");

/** The tray menu: Swift and its status, where it sits, smart placement, then the actions. */
function drawTray(v: TrayView): void {
  const tray = (value: string, extra: Record<string, unknown> = {}) => () => act("tray", { value, ...extra });
  const typeKeys = v.typeKey ? keys(v.typeKey) : null;
  root.replaceChildren(
    el(
      "section",
      { class: "tray", role: "menu", "aria-label": "Swift" },
      el("div", { class: "tray-head" }, el("span", { class: "orb", "aria-hidden": "true" }), el("span", {}, el("b", {}, "Swift"), el("span", {}, v.status))),
      el("div", { class: "tray-sep" }),
      el("div", { class: "tray-block" },
        el("div", { class: "tray-row" }, "Position", el("span", {}, anchorName(v.anchor))),
        el("div", { class: "picker", role: "radiogroup", "aria-label": "Position" },
          ...ANCHORS.map((a) => el("button", {
            role: "radio", "aria-checked": String(a === v.anchor), "aria-label": anchorName(a), title: anchorName(a),
            onclick: tray("anchor", { text: a }),
          })))),
      el("div", { class: "tray-block" },
        el("div", { class: "tray-row" }, "Smart placement",
          el("button", { class: "switch", role: "switch", "aria-checked": String(v.smart), "aria-label": "Smart placement", onclick: tray("smart") })),
        el("p", { class: "tray-help" }, "Moves away from the text cursor and full-screen apps.")),
      el("div", { class: "tray-sep" }),
      el("button", { class: "tray-item", role: "menuitem", onclick: tray("pause") }, icon(v.paused ? "play" : "pause"), v.paused ? "Resume listening" : "Pause listening"),
      el("button", { class: "tray-item", role: "menuitem", onclick: tray("type") }, icon("keyboard"), "Type to Swift", typeKeys),
      el("button", { class: "tray-item", role: "menuitem", onclick: tray("settings") }, icon("settings"), "Settings"),
      el("div", { class: "tray-sep" }),
      el("button", { class: "tray-item", role: "menuitem", onclick: tray("quit") }, icon("power"), "Quit Swift"),
    ),
  );
  watchOutside();
}

/** The live view, redrawn on every update: the body keeps its scroll place, or stays at the end. */
function drawLive(v: LiveView): void {
  const old = root.querySelector<HTMLElement>(".live-body");
  const atEnd = !old || old.scrollHeight - old.scrollTop - old.clientHeight < 24;
  const top = old?.scrollTop ?? 0;
  const runId = v.runId;
  root.replaceChildren(V.liveCard(v, {
    close: () => act("live-close", { runId }),
    stop: () => act("live-stop", { runId }),
    link: (url) => void invoke("open_link", { url }).catch(() => {}),
    app: () => act("live-app", { runId }),
    answer: () => act("live-answer", { runId }),
  }));
  const body = root.querySelector<HTMLElement>(".live-body");
  if (!body) return;
  // Writing: follow the newest paragraph, unless the owner scrolled up to read.
  body.scrollTop = atEnd && v.written && v.running ? body.scrollHeight : top;
  body.addEventListener("scroll", touch, { passive: true });
}

function draw(): void {
  if (!view) return;
  switch (view.kind) {
    case "stack":
      if (view.expanded) {
        root.replaceChildren(V.stackOpen(view, {
          item: (id, item) => act("stack-item", { id, item }),
          collapse: () => act("stack-collapse"),
          selected,
          select: (id) => {
            selected = id;
            for (const row of root.querySelectorAll<HTMLElement>(".stack-row")) row.setAttribute("aria-selected", String(row.dataset.id === id));
          },
        }));
        watchOutside();
      } else {
        root.replaceChildren(V.stackClosed(view, { "data-click": "stack" }));
      }
      break;
    case "type":
      drawType(view);
      break;
    case "tray":
      drawTray(view);
      break;
    case "request":
      root.replaceChildren(V.chip(view, { "data-click": "focus" }));
      break;
    case "live":
      drawLive(view);
      break;
    case "reader":
      if (view.chip) {
        root.replaceChildren(
          el("div", { class: "chip", role: "button", title: "Open the answer again", "data-click": "open" },
            el("span", { class: "chip-icon" }, icon("info")),
            el("span", { class: "chip-text" }, el("span", { class: "chip-title" }, view.title), el("span", { class: "chip-sub" }, "Open the answer"))),
        );
      } else {
        const v = view;
        const copy = el("button", { class: "btn btn--ghost", title: "Copy the answer" }, icon("copy"), "Copy");
        copy.addEventListener("click", async () => {
          try {
            await invoke("copy_text", { text: plain(v) });
            copy.replaceChildren(icon("check"), "Copied");
          } catch {
            copy.replaceChildren("Couldn't copy");
          }
          window.setTimeout(() => copy.replaceChildren(icon("copy"), "Copy"), 1600);
        });
        const body = el("div", { class: "reader-body answer", tabindex: "0" }, el("p", {}, v.summary), details(v.details));
        body.addEventListener("scroll", touch, { passive: true });
        root.replaceChildren(
          el(
            "section",
            { class: "reader", role: "region", "aria-label": v.title },
            el("header", { class: "card-head", title: "Drag to move" },
              el("p", { class: "words" }, v.title),
              el("button", { class: "icon-btn", "aria-label": "Close", title: "Close", onclick: () => act("close") }, icon("x"))),
            body,
            el("footer", { class: "card-foot" }, el("span", { class: "foot-gap" }), copy),
          ),
        );
      }
      break;
  }
  fit();
}

/** The window takes the size of what it shows. */
function fit(): void {
  const node = root.firstElementChild as HTMLElement | null;
  if (!node) return;
  const r = node.getBoundingClientRect();
  void invoke("fit_pane", { label, w: Math.ceil(r.width), h: Math.ceil(r.height) }).catch(() => {});
}
new ResizeObserver(fit).observe(root);

/** The owner is looking at the reader: it doesn't shrink to a chip yet. At most every few seconds. */
function touch(): void {
  if ((view?.kind !== "reader" && view?.kind !== "live") || Date.now() - lastTouch < 3000) return;
  lastTouch = Date.now();
  if (view.kind === "live") act("live-touch", { runId: view.runId });
  else act("touch");
}
root.addEventListener("pointermove", touch, { passive: true });

root.addEventListener("pointerdown", async (ev) => {
  const target = ev.target as HTMLElement;
  if (ev.button !== 0 || target.closest("button, input, .reader-body, .live-body") || view?.kind === "tray") return;
  // No text selection or native drag while Rust moves the window (check 19, 2026-10-27).
  ev.preventDefault();
  const clicked = target.closest<HTMLElement>("[data-click], .stack-row");
  const click = clicked?.dataset.click ?? (clicked?.classList.contains("stack-row") ? "item" : undefined);
  let moved = false;
  try {
    moved = await invoke<boolean>("drag_pane", { label });
  } catch {
    moved = false;
  }
  if (moved || !click) return;
  if (click === "stack") {
    const now = Date.now();
    if (now - lastClick < DOUBLE_MS) act("stack-expand");
    lastClick = now;
  } else if (click === "item" && clicked?.dataset.id) {
    // A click on a row selects it (its buttons show); Open is one of them.
    selected = clicked.dataset.id;
    for (const row of root.querySelectorAll<HTMLElement>(".stack-row")) row.setAttribute("aria-selected", String(row.dataset.id === selected));
  } else if (view?.kind === "request") {
    act(click, { runId: view.runId });
  } else {
    act(click);
  }
});

// Clicking away from the text box closes it (it keeps what was typed for next time).
window.addEventListener("blur", () => {
  const input = root.querySelector<HTMLInputElement>(".type-input");
  if (view?.kind === "type" && input) act("type-close", { text: input.value });
});

void listen<{ label: string; view: PaneView }>("pane", ({ payload }) => {
  if (payload.label !== label) return;  // events reach every window: only ours
  view = payload.view;
  draw();
});

// Elapsed time on a request chip or a live view.
window.setInterval(() => {
  if ((view?.kind !== "request" && view?.kind !== "live") || !view.running) return;
  const node = root.querySelector<HTMLElement>(".chip-time");
  if (node) node.textContent = V.elapsed(view.startedMs);
}, 1000);

// The main window sends what to show once this window is listening.
act("ready");

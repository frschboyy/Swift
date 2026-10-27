// A pane window (ADR-015 §3): another request as a chip, or a long answer in the reader.
//
// It draws only what the main window tells it (the ``pane`` event, for its own label) and sends
// clicks back (``pane-action``); the main window keeps the backend connection and the presenter.
// The whole window is the pane, so it is clickable all over: no click-through regions. Pressing
// anywhere but a button drags it (Rust follows the cursor and remembers where it went, per kind);
// a press that doesn't move is a click.

import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { el, icon } from "./dom";
import type { PaneView } from "./panes";
import type { ResultDetails } from "./protocol";

const label = getCurrentWindow().label;
const root = document.getElementById("stage")!;
let view: PaneView | null = null;
let lastTouch = 0;

document.body.classList.add("pane-body");
root.dataset.pane = "true";
// The reader is at most 70 % of the screen's height; past that its body scrolls.
root.style.setProperty("--reader-max", `${Math.max(240, Math.round(screen.availHeight * 0.7) - 64)}px`);
root.replaceChildren();

const act = (action: string, extra: Record<string, unknown> = {}): void => {
  void emitTo("overlay", "pane-action", { label, action, ...extra }).catch(() => {});
};

const elapsed = (startedMs: number): string => {
  const s = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function details(d: ResultDetails | null): HTMLElement | null {
  if (!d) return null;
  switch (d.kind) {
    case "text":
      return el("p", { class: "reader-text" }, d.text);
    case "list":
      return el("ul", { class: "result-list" }, ...d.items.map((i) => el("li", {}, i)));
    case "table":
      return el(
        "div",
        { class: "table-wrap" },
        el(
          "table",
          { class: "result-table" },
          el("thead", {}, el("tr", {}, ...d.columns.map((c) => el("th", { scope: "col" }, c)))),
          el("tbody", {}, ...d.rows.map((r) => el("tr", {}, ...r.map((c) => el("td", {}, c))))),
        ),
      );
  }
}

function plain(v: Extract<PaneView, { kind: "reader" }>): string {
  const d = v.details;
  const extra = !d ? "" : d.kind === "text" ? d.text : d.kind === "list" ? d.items.map((i) => `- ${i}`).join("\n")
    : [d.columns, ...d.rows].map((r) => r.join("\t")).join("\n");
  return [v.summary, extra].filter(Boolean).join("\n\n");
}

function draw(): void {
  if (!view) return;
  if (view.kind === "request") {
    const v = view;
    root.replaceChildren(
      el(
        "div",
        { class: `chip chip--${v.state}`, role: "button", title: "Bring this request to the front", "data-click": "focus" },
        el("span", { class: v.running ? "spinner spinner--small" : "row-dot", "aria-hidden": "true" }),
        el("span", { class: "row-title" }, v.title),
        el("span", { class: "row-activity" }, v.label),
        v.running ? el("span", { class: "elapsed" }, elapsed(v.startedMs)) : null,
      ),
    );
  } else if (view.chip) {
    root.replaceChildren(
      el(
        "div",
        { class: "chip chip--reader", role: "button", title: "Open the answer again", "data-click": "open" },
        icon("info"),
        el("span", { class: "row-title" }, view.title),
        el("span", { class: "row-activity" }, "Open"),
      ),
    );
  } else {
    const v = view;
    const copy = el("button", { class: "btn btn--ghost btn--small", title: "Copy the answer" }, icon("copy"), "Copy");
    copy.addEventListener("click", async () => {
      try {
        await invoke("copy_text", { text: plain(v) });
        copy.replaceChildren(icon("check"), "Copied");
      } catch {
        copy.replaceChildren("Couldn't copy");
      }
      window.setTimeout(() => copy.replaceChildren(icon("copy"), "Copy"), 1600);
    });
    const body = el("div", { class: "reader-body", tabindex: "0" }, el("p", { class: "summary" }, v.summary), details(v.details));
    body.addEventListener("scroll", touch, { passive: true });
    root.replaceChildren(
      el(
        "section",
        { class: "card card--in reader", role: "region", "aria-label": v.title },
        el(
          "header",
          { class: "card-head", title: "Drag to move" },
          icon("info"),
          el("span", { class: "card-title card-title--sentence" }, v.title),
          el("span", { class: "head-extra" }, copy),
          el("button", { class: "icon-btn", "aria-label": "Close", title: "Close", onclick: () => act("close") }, icon("x")),
        ),
        body,
      ),
    );
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
  if (view?.kind !== "reader" || Date.now() - lastTouch < 3000) return;
  lastTouch = Date.now();
  act("touch");
}
root.addEventListener("pointermove", touch, { passive: true });

root.addEventListener("pointerdown", async (ev) => {
  const target = ev.target as HTMLElement;
  if (ev.button !== 0 || target.closest("button, .reader-body")) return;
  const click = target.closest<HTMLElement>("[data-click]")?.dataset.click;
  let moved = false;
  try {
    moved = await invoke<boolean>("drag_pane", { label });
  } catch {
    moved = false;
  }
  if (!moved && click && view?.kind === "request") act(click, { runId: view.runId });
  else if (!moved && click) act(click);
});

void listen<{ label: string; view: PaneView }>("pane", ({ payload }) => {
  if (payload.label !== label) return;  // events reach every window: only ours
  view = payload.view;
  draw();
});

// Elapsed time on a request chip.
window.setInterval(() => {
  if (view?.kind !== "request" || !view.running) return;
  const node = root.querySelector<HTMLElement>(".elapsed");
  if (node) node.textContent = elapsed(view.startedMs);
}, 1000);

// The main window sends what to show once this window is listening.
act("ready");

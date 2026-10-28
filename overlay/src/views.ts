// The Capsule design's chip and waiting stack as elements (ADR-017), shared by the pane windows
// (pane.ts) and the main window's inline fallback where there are no pane windows (the dev
// harness). Text goes through textContent only (dom.ts ``el``).

import { el, icon } from "./dom";
import type { PaneView } from "./panes";
import { countLine, nextLine, type StackView } from "./stack";

type RequestView = Extract<PaneView, { kind: "request" }>;

export const elapsed = (startedMs: number, now = Date.now()): string => {
  const s = Math.max(0, Math.floor((now - startedMs) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** The chip's state icon: an orbit while it runs, an amber shield when it needs the owner, a green
 * check when its answer is ready. Each with a word beside it (the activity line). */
function chipIcon(v: RequestView): HTMLElement {
  if (v.state === "confirm") return el("span", { class: "chip-icon" }, el("span", { class: "needs-icon" }, icon("shield")));
  if (v.state === "result") return el("span", { class: "chip-icon" }, el("span", { class: "ready-icon" }, icon("check")));
  if (v.running) return el("span", { class: "chip-icon" }, el("span", { class: "spinner spinner--small" }));
  return el("span", { class: "chip-icon" }, el("span", { class: "ended-icon" }));
}

/** What the chip's second line says. */
export function chipLine(v: RequestView): string {
  if (v.state === "confirm") return "Needs your OK";
  if (v.state === "result") return "Ready to read";
  return v.label;
}

/** Another request, as a chip: click brings it forward, drag moves it (the caller wires both). */
export function chip(v: RequestView, attrs: Record<string, string | boolean | ((ev: Event) => void)> = {}): HTMLElement {
  return el(
    "div",
    { class: `chip chip--${v.state}`, role: "button", title: `${v.words}\nClick to bring it forward`, "aria-label": `${v.title}: ${chipLine(v)}`, ...attrs },
    chipIcon(v),
    el("span", { class: "chip-text" }, el("span", { class: "chip-title" }, v.title), el("span", { class: "chip-sub" }, chipLine(v))),
    v.running ? el("span", { class: "chip-time" }, elapsed(v.startedMs)) : null,
    el("span", { class: "chip-open" }, "Open"),
  );
}

/** The closed stack: two layers behind the top one, the count and what comes next. */
export function stackClosed(v: StackView, attrs: Record<string, string | boolean | ((ev: Event) => void)> = {}): HTMLElement {
  const n = v.items.length;
  return el(
    "div",
    {
      class: `stack${v.items.some((i) => i.fresh) ? " stack--fresh" : ""}`, role: "button",
      title: "Double-click to see what needs you", "aria-label": `${countLine(n)}. ${nextLine(v)}`, ...attrs,
    },
    n > 2 ? el("span", { class: "stack-layer stack-layer--1" }) : null,
    n > 1 ? el("span", { class: "stack-layer stack-layer--2" }) : null,
    el("div", { class: "stack-top" },
      el("span", { class: "badge" }, String(n)),
      el("span", { class: "stack-text" }, el("span", { class: "stack-count" }, countLine(n)), el("span", { class: "stack-next" }, nextLine(v)))),
  );
}

export type StackHandlers = {
  item: (id: string, action: "open" | "skip" | "end") => void;
  collapse: () => void;
  // The row the owner last pointed at (its buttons show).
  selected?: string | null;
  select?: (id: string) => void;
};

/** The open stack: every card, its whole title, why it waits, and Open / Skip / End. */
export function stackOpen(v: StackView, h: StackHandlers): HTMLElement {
  const selected = h.selected && v.items.some((i) => i.id === h.selected) ? h.selected : v.items[0]?.id;
  const row = (i: StackView["items"][number]): HTMLElement =>
    el(
      "li",
      {
        class: `stack-row stack-row--${i.icon}${i.fresh ? " stack-row--fresh" : ""}`, "data-id": i.id,
        "aria-selected": String(i.id === selected), onpointerenter: () => h.select?.(i.id),
      },
      icon(i.icon),
      el("span", { class: "stack-title" }, i.title),
      el("span", { class: "stack-reason" }, i.line),
      el("span", { class: "stack-actions" },
        el("button", { class: "btn btn--primary btn--small", onclick: () => h.item(i.id, "open") }, i.open),
        el("button", { class: "btn btn--ghost btn--small", title: "Back to the stack, last in line", onclick: () => h.item(i.id, "skip") }, "Skip"),
        el("button", { class: "btn btn--ghost btn--small", title: "End it: it won't come back", onclick: () => h.item(i.id, "end") }, "End")),
    );
  return el(
    "section",
    { class: "stack-open", role: "region", "aria-label": "Needs you" },
    el("header", { class: "stack-head", title: "Drag to move" },
      el("b", {}, "Needs you"),
      el("span", {}, String(v.items.length)),
      el("button", { class: "icon-btn", "aria-label": "Fold up", title: "Fold up (Esc)", onclick: () => h.collapse() }, icon("collapse"))),
    el("ul", { class: "stack-list" }, ...v.items.map(row)),
  );
}

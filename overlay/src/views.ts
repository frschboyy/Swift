// The Capsule design's chip and waiting stack as elements (ADR-017), shared by the pane windows
// (pane.ts) and the main window's inline fallback where there are no pane windows (the dev
// harness). Text goes through textContent only (dom.ts ``el``).
// ADR-017 §7: the live view of a running request, the same way.

import { el, icon } from "./dom";
import type { LiveView, Source } from "./live";
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

/** Another request, as a chip: click brings it forward, drag moves it (the caller wires both).
 * While it works, Watch (shown on hover) opens its live view: ``watch``, or its ``data-click``. */
export function chip(v: RequestView, attrs: Record<string, string | boolean | ((ev: Event) => void)> = {}, watch?: () => void): HTMLElement {
  const watchable = v.running && v.state !== "confirm" && v.state !== "queued";
  return el(
    "div",
    { class: `chip chip--${v.state}`, role: "button", title: `${v.words}\nClick to bring it forward`, "aria-label": `${v.title}: ${chipLine(v)}`, ...attrs },
    chipIcon(v),
    el("span", { class: "chip-text" }, el("span", { class: "chip-title" }, v.title), el("span", { class: "chip-sub" }, chipLine(v))),
    v.running ? el("span", { class: "chip-time" }, elapsed(v.startedMs)) : null,
    watchable
      ? el("span", {
          class: "chip-watch", role: "button", "data-click": "watch", title: "Watch it work",
          ...(watch ? { onclick: (ev: Event) => { ev.stopPropagation(); watch(); } } : {}),
        }, "Watch")
      : null,
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

// ---- the live view (ADR-017 §7) ----------------------------------------------------------

export type LiveHandlers = {
  close: () => void;
  stop: () => void;
  link: (url: string) => void;
  app: () => void;
  answer: () => void;
  copy?: () => void;
};

const SOURCE_STATE: Record<Source["state"], string> = { found: "Found", reading: "Reading", read: "Read", failed: "Couldn't read" };

function sourceIcon(s: Source): HTMLElement {
  if (s.state === "reading") return el("span", { class: "src-state src-state--reading" }, el("span", { class: "spinner spinner--small" }));
  if (s.state === "read") return el("span", { class: "src-state src-state--read" }, icon("check"));
  if (s.state === "failed") return el("span", { class: "src-state src-state--failed" }, icon("x"));
  return el("span", { class: "src-state src-state--found" }, el("span", { class: "src-dot" }));
}

function sourceRow(s: Source, link: (url: string) => void): HTMLElement {
  return el(
    "li",
    {},
    el(
      "button",
      { class: `live-src live-src--${s.state}`, title: `${s.url}\nOpen in your browser`, "aria-label": `${s.title || s.site}, ${s.site}: ${SOURCE_STATE[s.state]}. Open in your browser`, onclick: () => link(s.url) },
      sourceIcon(s),
      el("span", { class: "src-text" }, el("span", { class: "src-title" }, s.title || s.site), el("span", { class: "src-site" }, `${s.site} · ${SOURCE_STATE[s.state]}`)),
      icon("external"),
    ),
  );
}

/** A request's live view: what it does now, what it wrote, the sources so far, its notes; Stop, or
 * once it ended the answer linked. The body scrolls; the caller keeps its place across updates. */
export function liveCard(v: LiveView, h: LiveHandlers, now = Date.now()): HTMLElement {
  const sections: HTMLElement[] = [];
  if (v.written) {
    const doc = el("div", { class: "live-doc", "aria-label": `What Swift wrote in ${v.written.app}` },
      ...v.written.text.split("\n").map((p) => el("p", {}, p)));
    sections.push(el("section", { class: "live-sec" }, el("h3", { class: "section-title" }, `Writing in ${v.written.app}`), doc));
  }
  if (v.sources.length) {
    const read = v.sources.filter((s) => s.state === "read").length;
    sections.push(el("section", { class: "live-sec" },
      el("h3", { class: "section-title" }, `Sources · ${v.sources.length}${read ? ` · ${read} read` : ""}`),
      el("ul", { class: "live-sources" }, ...v.sources.map((s) => sourceRow(s, h.link)))));
  }
  if (v.notes.length) {
    sections.push(el("section", { class: "live-sec" },
      el("h3", { class: "section-title" }, "Notes"),
      el("ul", { class: "live-notes" }, ...v.notes.map((n) => el("li", {}, n)))));
  }
  if (!sections.length) {
    sections.push(el("p", { class: "muted live-empty" }, v.running ? "Sources, notes and what it writes show up here as they come." : "Nothing was found or written."));
  }
  const status = v.running
    ? el("span", { class: "spinner", "aria-hidden": "true" })
    : v.ended?.status === "done"
      ? el("span", { class: "ok-dot" }, icon("check"))
      : el("span", { class: "ended-icon" });
  const foot: (HTMLElement | null)[] = v.running
    ? [
        el("span", { class: "hint foot-gap" }, "Live"),
        v.written ? el("button", { class: "btn btn--ghost", title: `Bring ${v.written.app} to the front`, onclick: () => h.app() }, icon("external"), `Show in ${v.written.app}`) : null,
        el("button", { class: "btn btn--ghost", title: "Stop this request only", onclick: () => h.stop() }, icon("stop"), "Stop"),
      ]
    : [
        el("span", { class: "hint foot-gap" }, "Closes by itself"),
        v.written ? el("button", { class: "btn btn--ghost", onclick: () => h.app() }, icon("external"), `Show in ${v.written.app}`) : null,
        v.ended?.answer ? el("button", { class: "btn btn--primary", onclick: () => h.answer() }, "Open the answer") : null,
      ];
  return el(
    "section",
    { class: `live${v.running ? " live--running" : " live--ended"}`, role: "region", "aria-label": `Live: ${v.title}` },
    el("header", { class: "card-head", title: "Drag to move" },
      el("span", { class: "live-badge" }, v.running ? "LIVE" : "DONE"),
      el("p", { class: "words" }, v.title),
      el("button", { class: "icon-btn", "aria-label": "Close", title: "Close", onclick: () => h.close() }, icon("x"))),
    el("div", { class: "status live-now" }, status,
      el("span", { class: "status-verb live-doing", "aria-live": "polite" }, v.doing),
      v.running ? el("span", { class: "elapsed chip-time" }, elapsed(v.startedMs, now)) : null),
    v.ended && v.ended.summary ? el("p", { class: "live-summary" }, v.ended.summary) : null,
    el("div", { class: "live-body", tabindex: "0" }, ...sections),
    v.hint ? el("p", { class: "voice-hint live-hint", "data-phase": "hint", "aria-live": "polite" }, v.hint) : null,
    el("footer", { class: "card-foot" }, ...foot),
  );
}

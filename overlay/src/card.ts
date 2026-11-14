// The one card renderer (ADR-019 Step B, SPEC §3). Every card in the main window is put together here
// from its state and its slots, top to bottom: the lead (what it is: the amber band, the question's tags,
// a one-line row), the origin (the owner's words), earlier turns, the body's blocks, the footer. main.ts
// decides what fills each slot and the presenter decides when the card shows; this only assembles it.
// Words go through textContent only (dom.ts ``el``).
//
// Where the next steps plug in, each a named place with nothing behind it yet:
// - B3, a look per state: ``data-card`` on the card's inside carries its ``CardState``.
// - B4, results laid out to fit: answer.ts ``Shape`` picks an answer's body, blocks.ts draws it; a
//   table, comparison, diagram, document preview or mind map is a new shape and a new block there.
// - B5, cards that grow: ``CardSpec.size``. Only "fit" today: the stylesheet's limit, scrolling past it.
// - B7, motion: main.ts ``showCard`` and ``hideCard`` are a card's only way in and out.

import { el, icon } from "./dom";

/** Halo's states (SPEC §4), and Swift's own notices, which aren't a run's. */
export type CardState = "working" | "asking" | "waiting" | "ok" | "done" | "stopped" | "failed" | "due" | "notice";

type Part = Node | string | null | undefined | false;

export type CardSpec = {
  state: CardState;
  /** The card's classes as today's stylesheet knows them ("result card--row"), each made ``card--…``. */
  look: string;
  role?: "status" | "alert";
  /** A layout for the inside besides the column: "row-line" or "due". */
  inner?: string;
  /** A click on the card itself (not a control): closing it. */
  onclick?: (ev: Event) => void;
  lead?: Part;
  origin?: Part;
  thread?: Part;
  body?: Part[];
  foot?: Part[];
  /** Its own time is on it (a question's pill): the fade bar stays hidden. */
  ownTime?: boolean;
  size?: "fit";
};

/** The card's inside, in SPEC §3's order. */
export function cardInside(s: CardSpec): HTMLElement {
  return el(
    "div",
    { class: s.inner ? `card-in ${s.inner}` : "card-in", "data-card": s.state, ...(s.onclick ? { onclick: s.onclick } : {}) },
    s.lead, s.origin, s.thread, ...(s.body ?? []),
    s.foot ? el("footer", { class: "card-foot" }, ...s.foot) : null,
  );
}

/** A 28 px icon button that doesn't also count as a click on the card. */
export const iconButton = (glyph: string, label: string, act: () => void, attrs: Record<string, string> = {}): HTMLElement =>
  el("button", { class: "icon-btn", "aria-label": label, title: label, ...attrs, onclick: (ev: Event) => { ev.stopPropagation(); act(); } }, icon(glyph));

/** A mark, a title and its lines: a failure, or one of Swift's notices. */
export const failBlock = (mark: Node, title: string, ...why: Part[]): HTMLElement =>
  el("div", { class: "fail" }, mark, el("div", {}, el("p", { class: "fail-title" }, title), ...why.map((w) => (w ? el("p", { class: "fail-why" }, w) : null))));

/** Swift's question, after an answer or during a run: said while it speaks, then waiting for the answer. */
export type Question = {
  asking: boolean;
  about: string;
  title: string;
  note?: string;
  pill: string;
  // Seconds shown on the pill (null: none), and the bar under it (ms; 0: none).
  secs: number | null;
  barMs: number;
  // The pill's words are read out as they change (a run's question).
  live?: boolean;
  options?: Node[];
  foot: Part[];
};

export function questionParts(q: Question): Pick<CardSpec, "lead" | "body" | "foot" | "ownTime"> {
  const pill = q.asking
    ? el("div", { class: "q-pill q-pill--speaking" }, el("span", { class: "wave", "aria-hidden": "true" }, ...Array.from({ length: 6 }, () => el("i", {}))),
        el("span", { class: "q-pill-text" }, q.pill))
    : el("div", { class: "q-pill" }, el("span", { class: "orb", "aria-hidden": "true" }),
        el("span", { class: "q-pill-text", ...(q.live ? { "aria-live": "polite" } : {}) }, q.pill),
        q.secs === null ? null : el("span", { class: "elapsed" }, `0:${String(q.secs).padStart(2, "0")}`),
        q.barMs ? el("span", { class: "timebar", style: `--fade-ms:${q.barMs}ms` }) : null);
  return {
    lead: el("div", { class: "q-tags" },
      el("span", { class: q.asking ? "tag" : "tag tag--fill" }, q.asking ? "Swift is asking" : "Waiting for you"),
      el("span", { class: "q-about" }, q.about)),
    body: [
      el("p", { class: "q-title" }, q.title),
      q.note ? el("p", { class: "q-note" }, q.note) : null,
      pill,
      q.options?.length ? el("div", { class: "q-options" }, ...q.options) : null,
    ],
    foot: q.foot,
    ownTime: true,
  };
}

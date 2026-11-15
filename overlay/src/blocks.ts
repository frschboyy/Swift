// Blocks: what a card's body is made of (ADR-019 SPEC §5), shared by the main window's cards and the
// reader pane. B4's result shapes are new blocks here. Text only, never HTML (dom.ts ``el``).

import { invoke } from "@tauri-apps/api/core";
import * as A from "./answer";
import { el, icon } from "./dom";
import type { Compare, Diagram, Idea, MindMap, ResultDetails } from "./protocol";

export { detailsText } from "./answer";

// Decision 4 (2026-11-15): the worker's choice is labelled as the worker's, never in Swift's voice and never
// naming the provider; the whole comparison sits under the worker's bar, as on the approval cards.
const COMPARE_BY = "Compared by the worker, not checked by Swift";

/** Options side by side: a heading per option, a row per measure, the worker's pick marked as its own. */
export function compareBlock(c: Compare, full: boolean): HTMLElement {
  const shown = full ? c.rows : c.rows.slice(0, 6);
  const mark = (i: number): string => (i === c.pick ? "compare-pick" : "");
  return el("div", { class: "compare facts-line--agent" },
    el("span", { class: "confirm-purpose-by" }, COMPARE_BY),
    c.title ? el("p", { class: "compare-title" }, c.title) : null,
    el("table", { class: "compare-table" },
      el("thead", {}, el("tr", {}, el("td", {}), ...c.items.map((item, i) =>
        el("th", { scope: "col", class: mark(i) }, item, i === c.pick ? el("span", { class: "compare-tag" }, A.PICK) : null)))),
      el("tbody", {}, ...shown.map((r) => el("tr", {}, el("th", { scope: "row" }, r.label),
        ...r.values.map((v, i) => el("td", { class: mark(i) }, v)))))),
    shown.length < c.rows.length ? el("p", { class: "answer-more" }, `and ${c.rows.length - shown.length} more rows (Read more shows them)`) : null,
    ...(c.text ? renderBlocks(c.text) : []));
}

const DIAGRAM_BY = "Drawn from the worker's outline, not checked by Swift";
/** Fired (bubbling) by a card's diagram too wide to read there: the answer then opens with Read more (main.ts). */
export const DIAGRAM_WIDE = "swift-diagram-wide";

/** A worker's diagram, drawn by Mermaid once it has loaded (only now: it's 2.8 MB). Until then it says so; if it
 *  doesn't draw, the words below it stand alone. ``full``: the reader's size, not the card's. */
export function diagramBlock(d: Diagram, full: boolean): HTMLElement {
  const stage = el("div", { class: "diagram-stage", role: "img", "aria-label": d.title ?? "Diagram" }, el("p", { class: "answer-more" }, "Drawing the diagram…"));
  const note = el("p", { class: "answer-more" }, "Too wide to read on the card (Read more shows all of it)");
  note.hidden = true;
  const block = el("div", { class: `diagram facts-line--agent${full ? " diagram--full" : ""}` },
    el("span", { class: "confirm-purpose-by" }, DIAGRAM_BY),
    d.title ? el("p", { class: "compare-title" }, d.title) : null,
    stage,
    note,
    ...(d.text ? renderBlocks(d.text) : []));
  // Shrunk into the card unless its labels would drop below Swift's smallest text (answer.ts diagramFits). Then
  // the card shows its start at full size and asks for Read more, which shows it whole at that size, scrolling.
  const size = (svg: SVGSVGElement): void => {
    const [, , w, h] = (svg.getAttribute("viewBox") ?? "").split(/[\s,]+/).map(Number);
    if (!(w > 0 && h > 0)) return;
    const label = Math.min(...[...svg.querySelectorAll("text")].map((t) => parseFloat(getComputedStyle(t).fontSize)).filter((px) => px > 0));
    const wide = !full && !A.diagramFits(w, h, Number.isFinite(label) ? label : 13, stage.clientWidth);
    if (full || wide) {
      svg.setAttribute("width", String(w));
      svg.setAttribute("height", String(h));
    }
    block.classList.toggle("diagram--wide", wide);
    // The cut edge fades: the right one when the width is what doesn't fit, else the bottom one.
    block.style.setProperty("--diagram-fade", stage.clientWidth / w < A.DIAGRAM_CARD_PX / h ? "to right" : "to bottom");
    note.hidden = !wide;
    if (wide) block.dispatchEvent(new CustomEvent(DIAGRAM_WIDE, { bubbles: true }));
  };
  // Mermaid bakes the colours into its SVG, so a theme change (data-theme on the window's root) draws it again.
  const themed = new MutationObserver(() => (block.isConnected ? paint() : themed.disconnect()));
  const paint = (): void => void import("./mermaid").then((m) => m.draw(d.source, block)).then((svg) => {
    stage.replaceChildren(svg ?? el("p", { class: "answer-more" }, "Swift couldn't draw this diagram."));
    if (svg) size(svg);
    const root = block.closest("[data-theme]");
    if (svg && root) themed.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
  });
  paint();
  return block;
}

const MINDMAP_BY = "Mapped by the worker, not checked by Swift";
const CARD_IDEAS = 12;  // swift/shapes.py CARD_IDEAS: more opens with Read more

/** A mind map drawn by Swift's own code: nested lists (the root, its branches beside it, their ideas beside
 *  those), so labels wrap instead of being cut and screen readers get the tree. On the card, the first twelve
 *  ideas; ``full`` shows them all. */
export function mindmapBlock(m: MindMap, full: boolean): HTMLElement {
  let left = full ? Infinity : CARD_IDEAS;
  let hidden = 0;
  const list = (ideas: Idea[], depth: number): HTMLElement | null => {
    const items = ideas.flatMap((i) => {
      if (left <= 0) return (hidden += 1 + count(i.children), []);
      left--;
      return [el("li", {}, el("span", { class: "mind-node" }, i.label), i.children.length ? list(i.children, depth + 1) : null)];
    });
    return items.length ? el("ul", { class: `mind-l${depth}` }, ...items) : null;
  };
  const tree = list(m.children, 1);
  return el("div", { class: "mindmap facts-line--agent" },
    el("span", { class: "confirm-purpose-by" }, MINDMAP_BY),
    m.title ? el("p", { class: "compare-title" }, m.title) : null,
    el("div", { class: "mind" }, el("span", { class: "mind-root" }, m.root), tree),
    hidden ? el("p", { class: "answer-more" }, `and ${hidden} more ideas (Read more shows them)`) : null,
    ...(m.text ? renderBlocks(m.text) : []));
}

const count = (ideas: Idea[]): number => ideas.reduce((n, i) => n + 1 + count(i.children), 0);

/** Paragraphs and lists with their marks, as elements (text only, never HTML). */
export function renderBlocks(text: string): HTMLElement[] {
  const runs = (rs: A.Run[]): Node[] =>
    rs.map((r) => (r.marks.includes("b") ? el("strong", {}, r.text) : r.marks.includes("i") ? el("em", {}, r.text) : r.marks.includes("code") ? el("code", {}, r.text) : document.createTextNode(r.text)));
  return A.blocks(text).map((b) => (b.kind === "p" ? el("p", {}, ...runs(b.runs)) : el("ul", {}, ...b.items.map((i) => el("li", {}, ...runs(i))))));
}

/** A table: its header row, then its rows. */
export const answerTable = (columns: string[], rows: string[][]): HTMLElement =>
  el(
    "table",
    { class: "answer-table" },
    el("thead", {}, el("tr", {}, ...columns.map((c) => el("th", { scope: "col" }, c)))),
    el("tbody", {}, ...rows.map((row) => el("tr", {}, ...row.map((c) => el("td", {}, c))))),
  );

/** ``full``: every row, for an answer opened with "Read more" (otherwise the first six). */
export function renderDetails(details: ResultDetails | null | undefined, full = false): HTMLElement | null {
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
        answerTable(details.columns, details.rows.slice(0, shown)),
        more > 0 ? el("p", { class: "answer-more" }, `and ${more} more rows (Read more shows them)`) : null,
      );
    }
    case "compare":
      return compareBlock(details, full);
    case "diagram":
      return diagramBlock(details, full);
    case "mindmap":
      return mindmapBlock(details, full);
  }
}

/** Copy, which says "Copied" for a moment. */
export function copyButton(text: string): HTMLElement {
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

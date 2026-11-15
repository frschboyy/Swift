// Blocks: what a card's body is made of (ADR-019 SPEC §5), shared by the main window's cards and the
// reader pane. B4's result shapes are new blocks here. Text only, never HTML (dom.ts ``el``).

import { invoke } from "@tauri-apps/api/core";
import * as A from "./answer";
import { el, icon } from "./dom";
import type { Compare, ResultDetails } from "./protocol";

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

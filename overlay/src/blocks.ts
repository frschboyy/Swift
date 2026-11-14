// Blocks: what a card's body is made of (ADR-019 SPEC §5), shared by the main window's cards and the
// reader pane. B4's result shapes are new blocks here. Text only, never HTML (dom.ts ``el``).

import { invoke } from "@tauri-apps/api/core";
import * as A from "./answer";
import { el, icon } from "./dom";
import type { ResultDetails } from "./protocol";

/** An answer's details as plain text: Copy, and the reader's Copy. */
export function detailsText(details: ResultDetails | null | undefined): string {
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

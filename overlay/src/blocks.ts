// Blocks: what a card's body is made of (ADR-019 SPEC §5), shared by the main window's cards and the
// reader pane. B4's result shapes are new blocks here. Text only, never HTML (dom.ts ``el``).

import { invoke } from "@tauri-apps/api/core";
import * as A from "./answer";
import { el, icon } from "./dom";
import type { Cards, Chart, Compare, Diagram, Idea, MindMap, Preview, ResultDetails, Tree } from "./protocol";
import { middleCut, startOpen, visibleRows } from "./tree";

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
    shown.length < c.rows.length ? el("p", { class: "answer-more" }, `and ${c.rows.length - shown.length} more rows (Show all shows them)`) : null,
    ...(c.text ? renderBlocks(c.text) : []));
}

const DIAGRAM_BY = "Drawn from the worker's outline, not checked by Swift";
/** Fired (bubbling) once a diagram is drawn, ``detail`` {wide, nodes}: too wide to read on the card, the answer
 *  opens with Show all (main.ts), which counts its nodes as steps (B5). */
export const DIAGRAM_DRAWN = "swift-diagram-drawn";

/** A worker's diagram, drawn by Mermaid once it has loaded (only now: it's 2.8 MB). Until then it says so; if it
 *  doesn't draw, the words below it stand alone. ``full``: the reader's size, not the card's. */
export function diagramBlock(d: Diagram, full: boolean): HTMLElement {
  const stage = el("div", { class: "diagram-stage", role: "img", "aria-label": d.title ?? "Diagram" }, el("p", { class: "answer-more" }, "Drawing the diagram…"));
  const note = el("p", { class: "answer-more" }, "Too wide to read on the card (Show all shows all of it)");
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
    // B5: the cut goes at a node boundary on the cut axis, never through a node.
    stage.style.maxHeight = stage.style.maxWidth = "";
    const nodes = [...svg.querySelectorAll<SVGGElement>("g.node")];
    if (wide && nodes.length && stage.clientWidth > 0) {  // not laid out yet (a first draw): the CSS clip stands
      const across = block.style.getPropertyValue("--diagram-fade") === "to right";
      const s = stage.getBoundingClientRect();
      const spans = nodes.map((g): [number, number] => {
        const r = g.getBoundingClientRect();
        return across ? [r.left - s.left, r.right - s.left] : [r.top - s.top, r.bottom - s.top];
      });
      const cut = A.nodeCut(spans, across ? stage.clientWidth : A.DIAGRAM_CARD_PX);
      if (cut > 0) stage.style[across ? "maxWidth" : "maxHeight"] = `${Math.ceil(cut) + 8}px`;
    }
    block.dispatchEvent(new CustomEvent(DIAGRAM_DRAWN, { bubbles: true, detail: { wide, nodes: nodes.length } }));
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
 *  those), so labels wrap instead of being cut and screen readers get the tree. On the card, twelve ideas taken
 *  level by level (answer.ts cardIdeas), so every branch shows; ``full`` shows them all. */
export function mindmapBlock(m: MindMap, full: boolean): HTMLElement {
  const kept = full ? null : A.cardIdeas(m.children, CARD_IDEAS);
  const hidden = kept ? count(m.children) - kept.size : 0;
  const list = (ideas: Idea[], depth: number): HTMLElement | null => {
    const items = ideas.filter((i) => !kept || kept.has(i)).map((i) =>
      el("li", {}, el("span", { class: "mind-node" }, i.label), i.children.length ? list(i.children, depth + 1) : null));
    return items.length ? el("ul", { class: `mind-l${depth}` }, ...items) : null;
  };
  const tree = list(m.children, 1);
  return el("div", { class: "mindmap facts-line--agent" },
    el("span", { class: "confirm-purpose-by" }, MINDMAP_BY),
    m.title ? el("p", { class: "compare-title" }, m.title) : null,
    el("div", { class: "mind" }, el("span", { class: "mind-root" }, m.root), tree),
    hidden ? el("p", { class: "answer-more" }, `and ${hidden} more ideas (Show all shows them)`) : null,
    ...(m.text ? renderBlocks(m.text) : []));
}

/** A PDF image or an Office text excerpt, both made locally from a file the worker was allowed to read. */
export function previewBlock(p: Preview, full: boolean): HTMLElement {
  const open = el("button", { class: "btn btn--ghost", title: `Open ${p.title}` }, "Open");
  open.addEventListener("click", async (event) => {
    event.stopPropagation();
    try {
      await invoke("open_preview", { path: p.path });
      open.textContent = "Opened";
    } catch {
      open.textContent = "Couldn't open";
    }
    window.setTimeout(() => { open.textContent = "Open"; }, 1600);
  });
  return el("div", { class: `preview-block${full ? " preview-block--full" : ""}` },
    el("span", { class: "confirm-purpose-by" }, "Preview made by Swift from this document"),
    el("p", { class: "preview-title" }, p.title),
    el("p", { class: "preview-meta" }, p.file_type.toUpperCase(), p.pages ? ` · ${p.pages} pages` : ""),
    p.thumbnail
      ? el("img", { class: "preview-thumbnail", src: `data:image/png;base64,${p.thumbnail}`, alt: `First page of ${p.title}` })
      : null,
    p.excerpt ? el("p", { class: "preview-excerpt" }, p.excerpt) : null,
    p.text ? el("p", { class: "answer-more" }, p.text) : null,
    open);
}

const CHART_BY = "Chart from the worker's data, not checked by Swift";
const CHART_CARD_POINTS = 6;
const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode<K extends keyof SVGElementTagNameMap>(
  tag: K, attributes: Record<string, string> = {}, text?: string,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function chartTickStep(range: number): number {
  const raw = range / 5 || range;
  const magnitude = 10 ** Math.max(-323, Math.floor(Math.log10(raw)));
  const fraction = raw / magnitude;
  return Math.max(Number.MIN_VALUE, (fraction < 1.5 ? 1 : fraction < 3 ? 2 : fraction < 7 ? 5 : 10) * magnitude);
}

/** A small accessible SVG chart; the card previews six categories and the reader shows all of them. */
export function chartBlock(c: Chart, full: boolean): HTMLElement {
  const shown = full ? c.x.length : Math.min(c.x.length, CHART_CARD_POINTS);
  const labels = c.x.slice(0, shown);
  const values = c.series.flatMap((s) => s.values);
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (c.type === "bar") {
    const padding = high === low ? Math.max(1, Math.abs(low) * 0.1) : (high - low) * 0.08;
    low = low < 0 ? low - padding : 0;
    high = high > 0 ? high + padding : 0;
    if (low === high) {
      low -= padding;
      high += padding;
    }
  } else {
    const padding = low === high ? Math.max(1, Math.abs(low) * 0.1) : (high - low) * 0.08;
    low -= padding;
    high += padding;
  }
  const step = chartTickStep(high - low);
  if (!(step > 0) || !Number.isFinite(step)) throw new RangeError("chart axis is out of range");
  low = c.type === "bar" && low === 0 ? 0 : Math.floor(low / step) * step;
  high = c.type === "bar" && high === 0 ? 0 : Math.ceil(high / step) * step;
  if (low === high) {
    low -= step;
    high += step;
  }

  const plot = { left: 62, top: 10, width: 402, height: 126 };
  const y = (value: number): number => plot.top + plot.height * (high - value) / (high - low);
  const pointX = (index: number): number => plot.left + plot.width * (index + 0.5) / shown;
  const number = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4, notation: "compact" });
  const description = c.series.map((s) =>
    `${s.name}: ${labels.map((label, i) => `${label}, ${number.format(s.values[i])}${c.unit ? ` ${c.unit}` : ""}`).join("; ")}`,
  ).join(". ");
  const svg = svgNode("svg", {
    class: "chart-plot", viewBox: "0 0 480 176", role: "img", "aria-label": description,
  });
  svg.append(svgNode("title", {}, c.title ?? `${c.type === "bar" ? "Bar" : "Line"} chart`));
  svg.append(svgNode("desc", {}, description));
  const ticks = Math.round((high - low) / step);
  for (let i = 0; i <= ticks; i++) {
    const value = high - step * i;
    const py = y(value);
    svg.append(
      svgNode("line", { x1: String(plot.left), y1: String(py), x2: String(plot.left + plot.width), y2: String(py), class: "chart-grid" }),
      svgNode("text", { x: String(plot.left - 8), y: String(py + 4), "text-anchor": "end", class: "chart-axis-label" }, number.format(value)),
    );
  }
  const groupWidth = plot.width / shown;
  for (const [i, label] of labels.entries()) {
    svg.append(svgNode("text", {
      x: String(pointX(i)), y: String(plot.top + plot.height + 22), "text-anchor": "middle", class: "chart-axis-label",
    }, label));
  }

  if (c.type === "bar") {
    const base = y(0);
    const slot = groupWidth / c.series.length;
    const barWidth = Math.min(20, slot * 0.72);
    c.series.forEach((s, seriesIndex) => s.values.slice(0, shown).forEach((value, i) => {
      const top = Math.min(base, y(value));
      svg.append(svgNode("rect", {
        x: String(plot.left + i * groupWidth + seriesIndex * slot + (slot - barWidth) / 2),
        y: String(top), width: String(barWidth), height: String(Math.max(1, Math.abs(base - y(value)))),
        class: `chart-bar chart-series-${seriesIndex}`,
      }));
    }));
  } else {
    c.series.forEach((s, seriesIndex) => {
      const points = s.values.slice(0, shown).map((value, i) => `${pointX(i)},${y(value)}`);
      svg.append(svgNode("polyline", {
        points: points.join(" "), class: `chart-line chart-series-${seriesIndex}`,
      }));
      s.values.slice(0, shown).forEach((value, i) => svg.append(svgNode("circle", {
        cx: String(pointX(i)), cy: String(y(value)), r: "3.5", class: `chart-point chart-series-${seriesIndex}`,
      })));
    });
  }

  return el("div", { class: `chart-block facts-line--agent${full ? " chart-block--full" : ""}` },
    el("span", { class: "confirm-purpose-by" }, CHART_BY),
    c.title ? el("p", { class: "chart-title" }, c.title) : null,
    c.unit ? el("p", { class: "chart-unit" }, `Unit: ${c.unit}`) : null,
    svg,
    el("ul", { class: "chart-legend", "aria-label": "Chart series" },
      ...c.series.map((s, i) => el("li", {},
        el("span", { class: `chart-legend-swatch chart-series-${i}${c.type === "line" ? " chart-legend-swatch--line" : ""}`, "aria-hidden": "true" }),
        el("span", {}, s.name)))),
    shown < c.x.length ? el("p", { class: "answer-more" }, `and ${c.x.length - shown} more categories (Show all shows them)`) : null,
    ...(c.text ? renderBlocks(c.text) : []));
}

const PROJECTS_BY = "Project cards from the worker, not checked by Swift";
const CARD_PROJECTS = 3;

const TREE_BY = "Listed by the worker, not checked by Swift";
const CARD_TREE_ROWS = 10;  // swift/shapes.py CARD_TREE_ROWS

/** B13: files and folders as a tree, read-only: folders open and close in place, a row is selected by a click.
 * No action from it (never a delete; opening a file is for later, from the file system, never the worker's text). */
export function treeBlock(t: Tree, full: boolean): HTMLElement {
  const open = new Set(startOpen(t.entries));
  let all = full;
  let selected: string | null = null;
  const list = el("ul", { class: "tree", role: "tree" });
  const draw = (): void => {
    const rows = visibleRows(t.entries, open);
    const shown = all ? rows : rows.slice(0, CARD_TREE_ROWS);
    list.replaceChildren(...shown.map((r) => el("li", {
      class: `tree-row${r.key === selected ? " tree-row--selected" : ""}`, role: "treeitem", style: `--depth:${r.depth}`,
      title: r.entry.name, ...(r.entry.folder ? { "aria-expanded": String(open.has(r.key)) } : {}),
      onclick: (ev: Event) => {
        ev.stopPropagation();
        if (r.entry.folder) open.has(r.key) ? open.delete(r.key) : open.add(r.key);
        selected = r.key;
        draw();
      },
    },
    el("span", { class: "tree-chev" }, r.entry.folder ? icon(open.has(r.key) ? "expand" : "chevron") : null),
    el("span", { class: `tree-icon${r.entry.folder ? " tree-icon--folder" : ""}` }, icon(r.entry.folder ? "folder" : "file")),
    el("span", { class: "tree-name" }, middleCut(r.entry.name)),
    r.entry.meta ? el("span", { class: "tree-meta" }, r.entry.meta) : null)),
    ...(rows.length > shown.length ? [el("li", { class: "tree-row tree-more", onclick: (ev: Event) => { ev.stopPropagation(); all = true; draw(); } },
      `+ ${rows.length - shown.length} more`)] : []));
  };
  draw();
  return el("div", { class: "tree-block facts-line--agent" },
    el("span", { class: "confirm-purpose-by" }, TREE_BY),
    t.title ? el("p", { class: "compare-title" }, t.title) : null,
    list,
    ...(t.text ? renderBlocks(t.text) : []));
}

/** A read-only project overview. Larger sets or text-heavy summaries open in the reader. */
export function cardsBlock(c: Cards, full: boolean): HTMLElement {
  const shown = full ? c.cards : c.cards.slice(0, CARD_PROJECTS);
  const hidden = c.cards.length - shown.length;
  const cards = shown.map((card) =>
    el("article", { class: "project-card" },
      el("h4", { class: "project-card-title" }, card.title),
      card.meta ? el("p", { class: "project-card-meta" }, card.meta) : null,
      card.detail ? el("p", { class: "project-card-detail" }, card.detail) : null));
  return el("div", { class: `project-cards-block facts-line--agent${full ? " project-cards-block--full" : ""}` },
    el("span", { class: "confirm-purpose-by" }, PROJECTS_BY),
    c.title ? el("p", { class: "project-cards-title" }, c.title) : null,
    el("div", { class: "project-cards" }, ...cards),
    hidden ? el("p", { class: "answer-more" }, `and ${hidden} more projects (Show all shows them)`)
      : !full && c.size === "expanded" ? el("p", { class: "answer-more" }, "Read more shows all project details") : null,
    ...(c.text ? renderBlocks(c.text) : []));
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
        more > 0 ? el("p", { class: "answer-more" }, `and ${more} more (Show all shows them)`) : null,
      );
    }
    case "table": {
      const more = details.rows.length - shown;
      return el(
        "div",
        {},
        answerTable(details.columns, details.rows.slice(0, shown)),
        more > 0 ? el("p", { class: "answer-more" }, `and ${more} more rows (Show all shows them)`) : null,
      );
    }
    case "compare":
      return compareBlock(details, full);
    case "diagram":
      return diagramBlock(details, full);
    case "mindmap":
      return mindmapBlock(details, full);
    case "preview":
      return previewBlock(details, full);
    case "chart":
      return chartBlock(details, full);
    case "cards":
      return cardsBlock(details, full);
    case "tree":
      return treeBlock(details, full);
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
      button.classList.add("btn--copied");  // A9: --ok check for 1.5 s
    } catch {
      button.replaceChildren("Couldn't copy");
    }
    window.setTimeout(() => { button.replaceChildren(icon("copy"), "Copy"); button.classList.remove("btn--copied"); }, 1500);
  });
  return button;
}

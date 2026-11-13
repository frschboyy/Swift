// B4 prototype (docs/design/b4-adaptive-results.md): a typed result, a shape plus its data, drawn by Swift's
// own code. The worker never sends markup: it sends data, `parseShape` checks it at the boundary, and
// anything that doesn't fit falls back to plain text. Words go through textContent only (dom.ts `el`).
// Dev only: nothing in src/ imports this. Halo Step B would move it into the card renderer's block catalog.

import { el } from "../../src/dom.ts";

export type Compare = { shape: "compare"; title?: string; items: string[]; rows: { label: string; values: string[] }[]; pick?: number };
export type Diagram = { shape: "diagram"; title?: string; nodes: { id: string; label: string }[]; edges: { from: string; to: string; label?: string }[] };
export type Shape = { shape: "text"; text: string } | Compare | Diagram;

const MAX_ITEMS = 4;
const MAX_ROWS = 12;
const MAX_NODES = 16;
const CELL_MAX = 160;

const str = (v: unknown, max = CELL_MAX): string | null => (typeof v === "string" && v.trim() ? v.trim().slice(0, max) : null);

/** The worker's result as a shape Swift can draw, or plain text when it isn't one. Never throws. */
export function parseShape(raw: unknown, fallback: string): Shape {
  const text: Shape = { shape: "text", text: fallback };
  if (!raw || typeof raw !== "object") return text;
  const r = raw as Record<string, unknown>;
  const title = str(r.title) ?? undefined;
  if (r.shape === "compare" && Array.isArray(r.items) && Array.isArray(r.rows)) {
    const items = r.items.map((i) => str(i));
    if (items.length < 2 || items.length > MAX_ITEMS || items.includes(null)) return text;
    const rows = r.rows.slice(0, MAX_ROWS).map((row) => {
      const o = (row ?? {}) as Record<string, unknown>;
      const values = Array.isArray(o.values) ? o.values.map((v) => str(v) ?? "—") : [];
      return { label: str(o.label) ?? "", values };
    });
    if (!rows.length || rows.some((row) => !row.label || row.values.length !== items.length)) return text;
    const pick = Number.isInteger(r.pick) && (r.pick as number) >= 0 && (r.pick as number) < items.length ? (r.pick as number) : undefined;
    return { shape: "compare", title, items: items as string[], rows, pick };
  }
  if (r.shape === "diagram" && Array.isArray(r.nodes) && Array.isArray(r.edges)) {
    const nodes = r.nodes.slice(0, MAX_NODES + 1).map((n) => ({ id: str((n as Record<string, unknown>)?.id, 40) ?? "", label: str((n as Record<string, unknown>)?.label, 60) ?? "" }));
    const ids = new Set(nodes.map((n) => n.id));
    if (!nodes.length || nodes.length > MAX_NODES || ids.size !== nodes.length || nodes.some((n) => !n.id || !n.label)) return text;
    const edges = r.edges.map((e) => {
      const o = (e ?? {}) as Record<string, unknown>;
      return { from: str(o.from, 40) ?? "", to: str(o.to, 40) ?? "", label: str(o.label, 40) ?? undefined };
    });
    if (edges.some((e) => !ids.has(e.from) || !ids.has(e.to) || e.from === e.to)) return text;
    return { shape: "diagram", title, nodes, edges };
  }
  return text;
}

/** Each node's layer: the longest path to it from a node nothing points at. A cycle's back edge is ignored. */
export function layers(d: Diagram): Map<string, number> {
  const rank = new Map(d.nodes.map((n) => [n.id, 0]));
  // shortcut: at most n relaxation passes, so a cycle stops instead of looping; fine for ≤16 nodes.
  for (let pass = 0; pass < d.nodes.length; pass++) {
    let moved = false;
    for (const e of d.edges) {
      const want = rank.get(e.from)! + 1;
      if (want > rank.get(e.to)! && want < d.nodes.length) { rank.set(e.to, want); moved = true; }
    }
    if (!moved) break;
  }
  return rank;
}

export function drawCompare(c: Compare): HTMLElement {
  const head = el("tr", {}, el("th", { scope: "col" }, ""), ...c.items.map((item, i) =>
    el("th", { scope: "col", class: i === c.pick ? "b4-pick" : "" }, item, i === c.pick ? el("span", { class: "b4-tag" }, "Best fit") : null)));
  const body = c.rows.map((row) => el("tr", {}, el("th", { scope: "row" }, row.label),
    ...row.values.map((v, i) => el("td", { class: i === c.pick ? "b4-pick" : "" }, v))));
  return el("table", { class: "b4-compare" }, el("thead", {}, head), el("tbody", {}, ...body));
}

const NS = "http://www.w3.org/2000/svg";
const svg = (tag: string, attrs: Record<string, string | number>, text?: string): SVGElement => {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text !== undefined) node.textContent = text;
  return node;
};

/** A layered flow, top to bottom, sized to the card's width. Swift lays it out; the worker only names the parts. */
export function drawDiagram(d: Diagram, width = 468): SVGElement {
  const rank = layers(d);
  const rows: string[][] = [];
  for (const n of d.nodes) (rows[rank.get(n.id)!] ??= []).push(n.id);
  const label = new Map(d.nodes.map((n) => [n.id, n.label]));
  const H = 40, GAP_Y = 34, PAD = 4;
  const pos = new Map<string, { x: number; y: number; w: number }>();
  rows.forEach((ids, r) => {
    const w = Math.min(200, (width - PAD * 2 - (ids.length - 1) * 12) / ids.length);
    const total = ids.length * w + (ids.length - 1) * 12;
    ids.forEach((id, i) => pos.set(id, { x: (width - total) / 2 + i * (w + 12), y: PAD + r * (H + GAP_Y), w }));
  });
  const height = PAD * 2 + rows.length * H + (rows.length - 1) * GAP_Y;
  const root = svg("svg", { class: "b4-diagram", viewBox: `0 0 ${width} ${height}`, width, height, role: "img" });
  root.append(svg("title", {}, d.title ?? "Diagram"));
  const defs = svg("defs", {});
  const marker = svg("marker", { id: "b4-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  marker.append(svg("path", { d: "M0 0L10 5L0 10z", class: "b4-arrowhead" }));
  defs.append(marker);
  root.append(defs);
  for (const e of d.edges) {
    const a = pos.get(e.from)!, b = pos.get(e.to)!;
    const down = b.y > a.y;
    const x1 = a.x + a.w / 2, y1 = down ? a.y + H : a.y, x2 = b.x + b.w / 2, y2 = down ? b.y : b.y + H;
    const my = (y1 + y2) / 2;
    root.append(svg("path", { d: `M${x1} ${y1}C${x1} ${my} ${x2} ${my} ${x2} ${y2}`, class: down ? "b4-edge" : "b4-edge b4-edge--back", "marker-end": "url(#b4-arrow)" }));
    if (e.label) root.append(svg("text", { x: (x1 + x2) / 2 + 6, y: my + 4, class: "b4-edge-label" }, e.label));
  }
  for (const [id, p] of pos) {
    root.append(svg("rect", { x: p.x, y: p.y, width: p.w, height: H, rx: 10, class: "b4-node" }));
    // shortcut: SVG text doesn't wrap, so a long label is cut by an average glyph width; measure it if labels clip.
    const full = label.get(id)!, fit = Math.floor((p.w - 16) / 7.4);
    const t = svg("text", { x: p.x + p.w / 2, y: p.y + H / 2 + 5, "text-anchor": "middle", class: "b4-node-label" }, full.length > fit ? full.slice(0, fit - 1) + "…" : full);
    t.append(svg("title", {}, full));
    root.append(t);
  }
  return root;
}

export function drawShape(s: Shape): Node {
  if (s.shape === "compare") return drawCompare(s);
  if (s.shape === "diagram") return drawDiagram(s);
  return el("p", {}, s.text);
}

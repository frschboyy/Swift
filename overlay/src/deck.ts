// The Deck (ADR-018): the other requests as labelled edges behind the card in front. Pure: no DOM.
//
// The backend's ``runs`` rows go to a stable order and to each edge's depth, inset and offset. New
// requests go on the far end, so nothing already on screen moves because of them. A request that
// leaves the front takes the slot of the one that came forward: a swap, the smallest move there is.

import type { Row } from "./presenter";

/** Edges drawn at most; past that, "+N" on the last one. */
export const MAX_EDGES = 3;
/** A request this young gets no edge yet: most answers beside a run take a few ms (the time), and an
 * edge that comes and goes at once is noise. */
export const EDGE_DELAY_MS = 600;
/** How long a new edge says "Got it: …" before it settles. */
export const ACK_MS = 2500;
/** How much of each edge shows past the one before it (CSS px), nearest the card first. */
export const PEEKS: readonly number[] = [32, 30, 28];
/** Each edge is this much narrower on each side than the one before it (CSS px). */
export const INSET_STEP = 10;

const ENDED: ReadonlySet<string> = new Set(["result", "error", "done"]);

export type Deck = {
  // Every row, in its place: the first is nearest the card.
  order: string[];
  // The request in front when ``runs`` last came.
  front: string | null;
  // Requests seen before, in front or behind: only one never seen lands.
  known: ReadonlySet<string>;
  // Requests saying "Got it", and until when.
  landing: ReadonlyMap<string, number>;
};

export const initialDeck: Deck = { order: [], front: null, known: new Set(), landing: new Map() };

/** The ``runs`` message (``rows`` without the one in front). */
export function onRows(d: Deck, focus: string | null, rows: Row[], now: number): Deck {
  const here = new Set(rows.map((r) => r.runId));
  const order = d.order.filter((id) => here.has(id));
  if (d.front !== focus && d.front !== null && here.has(d.front) && !order.includes(d.front)) {
    const left = focus === null ? -1 : d.order.indexOf(focus);
    const slot = left < 0 ? 0 : d.order.slice(0, left).filter((id) => here.has(id)).length;
    order.splice(slot, 0, d.front);
  }
  const landing = new Map([...d.landing].filter(([id, until]) => here.has(id) && until > now));
  for (const r of rows) {
    if (order.includes(r.runId)) continue;
    order.push(r.runId);
    if (!d.known.has(r.runId) && !ENDED.has(r.state)) landing.set(r.runId, Math.max(r.startedMs + EDGE_DELAY_MS, now) + ACK_MS);
  }
  const known = new Set(d.known);
  for (const r of rows) known.add(r.runId);
  if (focus !== null) known.add(focus);
  return { order, front: focus, known, landing };
}

export type Edge = {
  row: Row;
  // 0 nearest the card; the first two steps also dim.
  depth: number;
  // From each side of the card, and from the card's edge to where this edge starts (CSS px).
  inset: number;
  offset: number;
  peek: number;
  landing: boolean;
  // Requests past the last edge ("+N").
  more: number;
};

/** One edge in place of them all, while a long answer is open: "2 more running". */
export type Fold = { count: number; running: number; needOk: number };

export type DeckView = { edges: Edge[]; fold: Fold | null; height: number };

/** What to draw now. ``folded``: Read more is open, so the deck gives way to one edge. */
export function deckView(d: Deck, rows: Row[], now: number, folded = false): DeckView {
  const byId = new Map(rows.map((r) => [r.runId, r]));
  const shown = d.order
    .map((id) => byId.get(id))
    .filter((r): r is Row => r !== undefined && now - r.startedMs >= EDGE_DELAY_MS);
  if (folded && shown.length > 1) {
    const running = shown.filter((r) => !ENDED.has(r.state)).length;
    const needOk = shown.filter((r) => r.state === "confirm").length;
    return { edges: [], fold: { count: shown.length, running, needOk }, height: PEEKS[0] };
  }
  const drawn = shown.slice(0, MAX_EDGES);
  let offset = 0;
  const edges = drawn.map((row, depth): Edge => {
    const edge = {
      row, depth, inset: INSET_STEP * (depth + 1), offset, peek: PEEKS[depth],
      // Its news comes first: an OK waiting or an answer ready never hides behind "Got it".
      landing: (d.landing.get(row.runId) ?? 0) > now && !ENDED.has(row.state) && row.state !== "confirm",
      more: depth === drawn.length - 1 ? shown.length - drawn.length : 0,
    };
    offset += PEEKS[depth];
    return edge;
  });
  return { edges, fold: null, height: offset };
}

/** The folded edge's words. */
export function foldLine(f: Fold): string {
  const all = f.running === f.count ? `${f.count} more running` : `${f.count} more`;
  return f.needOk ? `${all} · ${f.needOk} ${f.needOk === 1 ? "needs" : "need"} your OK` : all;
}

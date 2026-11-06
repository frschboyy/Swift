// The Deck (ADR-018): the other requests as labelled edges behind the card in front. Pure: no DOM.
//
// The backend's ``runs`` rows go to a stable order and to each edge's depth, inset and offset. New
// requests go on the far end, so nothing already on screen moves because of them. A request that
// leaves the front takes the slot of the one that came forward: a swap, the smallest move there is.
//
// A request's id changes when its run starts ("req-…" to the provider's id). It's the same request: it
// keeps its place, its element (``key``) and what it was saying, so it never lands twice.

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
  // When each row started, which doesn't change with its id, and the key its element is drawn under.
  started: ReadonlyMap<string, number>;
  keys: ReadonlyMap<string, string>;
};

export const initialDeck: Deck = { order: [], front: null, known: new Set(), landing: new Map(), started: new Map(), keys: new Map() };

/** The key a request's element is drawn under. */
export const keyOf = (d: Deck, runId: string | null): string | null => (runId === null ? null : d.keys.get(runId) ?? runId);

/** The ``runs`` message (``rows`` without the one in front). ``onCard``: the request on the card until
 * now. A request alone gets no ``runs``, so the first one can be what tells it's no longer in front. */
export function onRows(d: Deck, focus: string | null, rows: Row[], now: number, onCard: string | null = null): Deck {
  const here = new Set(rows.map((r) => r.runId));
  // The same request under its new id, where the old one has gone and it started at the same moment.
  const gone = d.order.filter((id) => !here.has(id));
  const renamed = new Map<string, string>();
  for (const r of rows) {
    if (d.known.has(r.runId) || r.runId === onCard) continue;
    const was = gone.find((id) => d.started.get(id) === r.startedMs && !renamed.has(id));
    if (was !== undefined) renamed.set(was, r.runId);
  }
  const named = (id: string): string => renamed.get(id) ?? id;
  const before = d.order.map(named);
  const order = before.filter((id) => here.has(id));
  const front = d.front ?? onCard;
  // What came forward left the slot: the old front takes it. Its id may have changed on the way.
  const left = focus !== null && before.includes(focus) ? before.indexOf(focus) : before.findIndex((id) => !here.has(id));
  if (front !== focus && front !== null && here.has(front) && !order.includes(front)) {
    const slot = left < 0 ? 0 : before.slice(0, left).filter((id) => here.has(id)).length;
    order.splice(slot, 0, front);
  }
  const keys = new Map(d.keys);
  for (const [was, id] of renamed) keys.set(id, keys.get(was) ?? was);
  // A row gone with nothing new under it, and the front new: that row is what came forward.
  const cameForward = focus !== null && !d.known.has(focus) && before[left] !== undefined && !here.has(before[left]) ? before[left] : null;
  if (cameForward !== null) keys.set(focus!, keys.get(cameForward) ?? cameForward);
  const landing = new Map([...d.landing].map(([id, until]): [string, number] => [named(id), until]).filter(([id, until]) => here.has(id) && until > now));
  for (const r of rows) {
    if (order.includes(r.runId)) continue;
    order.push(r.runId);
    if (!d.known.has(r.runId) && r.runId !== front && !ENDED.has(r.state)) landing.set(r.runId, Math.max(r.startedMs + EDGE_DELAY_MS, now) + ACK_MS);
  }
  const known = new Set(d.known);
  const started = new Map(rows.map((r): [string, number] => [r.runId, r.startedMs]));
  for (const r of rows) known.add(r.runId);
  if (focus !== null) known.add(focus);
  if (front !== null) known.add(front);
  return { order, front: focus, known, landing, started, keys };
}

export type Edge = {
  row: Row;
  // What its element is drawn under, whatever its id is now.
  key: string;
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
      row, key: keyOf(d, row.runId)!, depth, inset: INSET_STEP * (depth + 1), offset, peek: PEEKS[depth],
      // Its news comes first: an OK waiting or an answer ready never hides behind "Got it".
      landing: (d.landing.get(row.runId) ?? 0) > now && !ENDED.has(row.state) && row.state !== "confirm",
      more: depth === drawn.length - 1 ? shown.length - drawn.length : 0,
    };
    offset += PEEKS[depth];
    return edge;
  });
  return { edges, fold: null, height: offset };
}

/** A request coming forward from an edge: the words its card should say, since the backend sends them
 * once. Null when the request on the card stays. */
export function wordsComingForward(rows: Row[], onCard: string | null, focus: string | null): string | null {
  if (focus === null || onCard === null || focus === onCard) return null;
  const row = rows.find((r) => r.runId === focus);
  return row ? row.words || row.title : null;
}

/** The folded edge's words. */
export function foldLine(f: Fold): string {
  const all = f.running === f.count ? `${f.count} more running` : `${f.count} more`;
  return f.needOk ? `${all} · ${f.needOk} ${f.needOk === 1 ? "needs" : "need"} your OK` : all;
}

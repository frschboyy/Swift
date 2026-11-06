// The Deck's pure part (ADR-018). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { ACK_MS, deckView, EDGE_DELAY_MS, foldLine, initialDeck, INSET_STEP, MAX_EDGES, onRows, PEEKS, type Deck } from "../src/deck.ts";
import type { Row } from "../src/presenter.ts";

const row = (runId: string, state = "working", startedMs = 0): Row => ({
  runId, threadId: null, title: runId, state, activity: null, app: null, startedMs, summary: "",
});
const NOW = 100_000;
const ids = (d: Deck, rows: Row[], now = NOW): string[] => deckView(d, rows, now).edges.map((e) => e.row.runId);
const go = (d: Deck, focus: string | null, rows: Row[], now = NOW): Deck => onRows(d, focus, rows, now);

test("a new request goes on the far end, and nothing already there moves", () => {
  let d = go(initialDeck, "a", [row("b")]);
  assert.deepEqual(d.order, ["b"]);
  d = go(d, "a", [row("c"), row("b")]);  // whatever order the backend names them in
  assert.deepEqual(d.order, ["b", "c"]);
  d = go(d, "a", [row("b"), row("c"), row("d")]);
  assert.deepEqual(d.order, ["b", "c", "d"]);
});

test("a row that goes leaves the others in their order", () => {
  const rows = [row("b"), row("c"), row("d")];
  const d = go(go(initialDeck, "a", rows), "a", [row("b"), row("d")]);
  assert.deepEqual(d.order, ["b", "d"]);
});

test("a request coming forward swaps with the one in front", () => {
  const rows = [row("b"), row("c"), row("d")];
  const d = go(go(initialDeck, "a", rows), "c", [row("b"), row("d"), row("a")]);
  assert.deepEqual(d.order, ["b", "a", "d"]);
  // And back again.
  assert.deepEqual(go(d, "a", [row("b"), row("c"), row("d")]).order, ["b", "c", "d"]);
});

test("the request in front gone with nothing named: the old front waits nearest the card", () => {
  const d = go(go(initialDeck, "a", [row("b")]), null, [row("b"), row("a")]);
  assert.deepEqual(d.order, ["a", "b"]);
});

test("each edge is narrower than the last and they stack by their peeks", () => {
  const rows = [row("b"), row("c"), row("d")];
  const v = deckView(go(initialDeck, "a", rows), rows, NOW);
  assert.deepEqual(v.edges.map((e) => e.depth), [0, 1, 2]);
  assert.deepEqual(v.edges.map((e) => e.inset), [INSET_STEP, 2 * INSET_STEP, 3 * INSET_STEP]);
  assert.deepEqual(v.edges.map((e) => e.offset), [0, PEEKS[0], PEEKS[0] + PEEKS[1]]);
  assert.equal(v.height, PEEKS[0] + PEEKS[1] + PEEKS[2]);
});

test("no rows: no deck, and it takes no height", () => {
  assert.deepEqual(deckView(initialDeck, [], NOW), { edges: [], fold: null, height: 0 });
});

test("at most three edges, then +N on the last", () => {
  const rows = ["b", "c", "d", "e", "f"].map((id) => row(id));
  const v = deckView(go(initialDeck, "a", rows), rows, NOW);
  assert.equal(v.edges.length, MAX_EDGES);
  assert.deepEqual(v.edges.map((e) => e.more), [0, 0, 2]);
  assert.equal(v.height, PEEKS[0] + PEEKS[1] + PEEKS[2]);
  const three = rows.slice(0, 3);
  assert.deepEqual(deckView(go(initialDeck, "a", three), three, NOW).edges.map((e) => e.more), [0, 0, 0]);
});

test("an instant answer never flashes an edge", () => {
  const young = [row("b", "working", NOW - EDGE_DELAY_MS + 1)];
  const d = go(initialDeck, "a", young);
  assert.deepEqual(ids(d, young), []);
  assert.deepEqual(ids(d, young, NOW + 1), ["b"]);
  // It answered at once: its row went before its edge ever showed.
  assert.deepEqual(ids(go(d, "a", []), [], NOW + 1), []);
});

test("a new request says Got it for 2.5 s from when its edge shows", () => {
  const rows = [row("b", "working", NOW)];
  const d = go(initialDeck, "a", rows);
  const at = (t: number) => deckView(d, rows, t).edges[0]?.landing;
  assert.equal(at(NOW + EDGE_DELAY_MS - 1), undefined);
  assert.equal(at(NOW + EDGE_DELAY_MS), true);
  assert.equal(at(NOW + EDGE_DELAY_MS + ACK_MS - 1), true);
  assert.equal(at(NOW + EDGE_DELAY_MS + ACK_MS), false);
});

test("only a request never seen lands: not one that ended, was in front, or came back", () => {
  const over = go(initialDeck, "a", [row("b", "result")]);
  assert.equal(deckView(over, [row("b", "result")], NOW).edges[0].landing, false);
  const swapped = [row("a")];
  const front = go(go(initialDeck, "a", []), "b", swapped);
  assert.equal(deckView(front, swapped, NOW).edges[0].landing, false);
  const back = go(go(go(initialDeck, "a", [row("b")], NOW - 10_000), "a", [], NOW - 5_000), "a", [row("b")]);
  assert.equal(deckView(back, [row("b")], NOW).edges[0].landing, false);
});

test("an OK waiting or an answer ready never hides behind Got it", () => {
  const d = go(initialDeck, "a", [row("b")]);
  const landing = (state: string) => deckView(d, [row("b", state)], NOW).edges[0].landing;
  assert.equal(landing("working"), true);
  assert.equal(landing("confirm"), false);
  assert.equal(landing("result"), false);
});

test("an answer read at length folds the deck to one edge, and an edge alone stays itself", () => {
  const rows = [row("b"), row("c", "confirm"), row("d", "result")];
  const d = go(initialDeck, "a", rows);
  const v = deckView(d, rows, NOW, true);
  assert.deepEqual(v.edges, []);
  assert.deepEqual(v.fold, { count: 3, running: 2, needOk: 1 });
  assert.equal(v.height, PEEKS[0]);
  const one = [row("b")];
  assert.deepEqual(deckView(go(initialDeck, "a", one), one, NOW, true).edges.map((e) => e.row.runId), ["b"]);
});

test("the folded edge says how many, and that an OK waits", () => {
  assert.equal(foldLine({ count: 2, running: 2, needOk: 0 }), "2 more running");
  assert.equal(foldLine({ count: 3, running: 2, needOk: 0 }), "3 more");
  assert.equal(foldLine({ count: 2, running: 2, needOk: 1 }), "2 more running · 1 needs your OK");
  assert.equal(foldLine({ count: 3, running: 3, needOk: 2 }), "3 more running · 2 need your OK");
});

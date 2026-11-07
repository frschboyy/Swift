// The Deck's pure part (ADR-018). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { ACK_MS, clockStart, deckView, EDGE_DELAY_MS, foldLine, initialDeck, INSET_STEP, keyOf, MAX_EDGES, onRows, PEEKS, wordsComingForward, type Deck } from "../src/deck.ts";
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

test("the first runs can be what says the one on the card went behind: it doesn't land", () => {
  const rows = [row("a")];
  const d = onRows(initialDeck, "b", rows, NOW, "a");
  assert.deepEqual(d.order, ["a"]);
  assert.equal(deckView(d, rows, NOW).edges[0].landing, false);
  assert.ok(d.known.has("a") && d.known.has("b"));
});

test("a request's id changes when its run starts: the same place, the same element, and it lands once", () => {
  const rows = [row("b", "working", 1000), row("req-x", "working", NOW - 2000), row("d", "working", 3000)];
  const d = go(go(initialDeck, "a", [], NOW - 5000), "a", rows, NOW - 1000);
  assert.equal(deckView(d, rows, NOW).edges[1].landing, true);
  const started = [row("b", "working", 1000), row("a-2", "working", NOW - 2000), row("d", "working", 3000)];
  const next = go(d, "a", started);
  assert.deepEqual(next.order, ["b", "a-2", "d"]);
  const edge = deckView(next, started, NOW).edges[1];
  assert.equal(edge.key, "req-x");
  assert.equal(edge.landing, true);  // still saying it, not starting again
  assert.equal(deckView(next, started, NOW + ACK_MS).edges[1].landing, false);
});

test("a request that goes as another comes isn't a rename unless it started at the same moment", () => {
  const d = go(initialDeck, "a", [row("b", "result", 1000)]);
  const next = go(d, "a", [row("c", "working", 2000)]);
  assert.deepEqual(next.order, ["c"]);
  assert.equal(keyOf(next, "c"), "c");
});

test("the backend's usual way: a young row comes forward under its new id, and the old front takes its slot", () => {
  const before = [row("a-1", "working", 1000), row("req-x", "working", NOW)];
  const d = go(go(initialDeck, "a-2", [row("a-1", "working", 1000)]), "a-2", before);
  const after = [row("a-1", "working", 1000), row("a-2", "working", 2000)];
  const next = go(d, "a-3", after);
  assert.deepEqual(next.order, ["a-1", "a-2"]);
  assert.equal(keyOf(next, "a-3"), "req-x");
  assert.equal(deckView(next, after, NOW + EDGE_DELAY_MS).edges[1].landing, false);
});

test("a card coming forward from an edge says that request's words", () => {
  const rows = [{ ...row("b"), title: "Tea", words: "research the history of tea" }, { ...row("c"), title: "Coffee" }];
  assert.equal(wordsComingForward(rows, "a", "b"), "research the history of tea");
  assert.equal(wordsComingForward(rows, "a", "c"), "Coffee");
  assert.equal(wordsComingForward(rows, "a", "a"), null);
  assert.equal(wordsComingForward(rows, null, "b"), null);
  assert.equal(wordsComingForward(rows, "a", "unknown"), null);
});

test("a card's clock is its own request's: a new request after one that came forward starts at now", () => {
  const forward = { runId: "b", startedMs: 1000 };
  assert.equal(clockStart(forward, "b", 9000), 1000);
  assert.equal(clockStart(forward, "c", 9000), 9000);
  assert.equal(clockStart(forward, null, 9000), 9000);
  assert.equal(clockStart(null, "b", 9000), 9000);
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

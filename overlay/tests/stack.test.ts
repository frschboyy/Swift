// The waiting stack (ADR-015 §9). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import type { StackEntry } from "../src/protocol.ts";
import { afterAction, collapse, countLine, expand, initialStack, onStack, reasonLine, stackView, FRESH_MS } from "../src/stack.ts";

const item = (id: string, kind: StackEntry["kind"] = "parked", reason = "stopped", since = 0): StackEntry =>
  ({ id, kind, title: `Title ${id}`, reason, since_ms: since, thread_id: null });

test("compressed by default; a double click expands it; outside or opening a card compresses it", () => {
  let s = onStack(initialStack, [item("parked:a"), item("card:1", "waiting", "waiting")], 0);
  assert.equal(stackView(s, 0)?.expanded, false);
  s = expand(s);
  assert.equal(stackView(s, 0)?.expanded, true);
  assert.equal(afterAction(s, "skip").expanded, true);  // skip or end: the owner may go on through the list
  assert.equal(afterAction(s, "end").expanded, true);
  assert.equal(afterAction(s, "open").expanded, false);  // the card comes forward by itself
  assert.equal(collapse(s).expanded, false);
});

test("nothing waiting: no stack, and it can't stay expanded", () => {
  let s = expand(onStack(initialStack, [item("parked:a")], 0));
  s = onStack(s, [], 1000);
  assert.equal(stackView(s, 1000), null);
  assert.equal(s.expanded, false);
  assert.equal(expand(s).expanded, false);
});

test("a card that just joined glows for a few seconds", () => {
  let s = onStack(initialStack, [item("parked:a")], 0);
  s = onStack(s, [item("parked:a"), item("card:2", "later", "later")], 10_000);
  assert.deepEqual(stackView(s, 10_000)?.items.map((i) => i.fresh), [false, true]);
  assert.deepEqual(stackView(s, 10_000 + FRESH_MS)?.items.map((i) => i.fresh), [false, false]);
});

test("each card says why it waits, in plain words; the open button says what happens", () => {
  const now = 5 * 60_000;
  assert.equal(reasonLine(item("card:1", "waiting", "waiting"), now), "Waiting behind another card");
  assert.equal(reasonLine(item("parked:a", "parked", "asked"), now), "Swift asked you something · 5 min ago");
  assert.equal(reasonLine(item("parked:a", "parked", "stopped", now - 30_000), now), "Stopped before it finished · just now");
  assert.equal(reasonLine(item("card:1", "held", "held"), now), "Kept while you were away");
  const view = stackView(onStack(initialStack, [item("parked:a"), item("card:1", "waiting", "waiting")], 0), 0)!;
  assert.deepEqual(view.items.map((i) => i.open), ["Resume", "Show"]);
  assert.equal(countLine(1), "1 card needs you");
  assert.equal(countLine(3), "3 cards need you");
});

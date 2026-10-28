// The waiting stack (ADR-015 §9). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import type { StackEntry } from "../src/protocol.ts";
import { afterAction, collapse, countLine, expand, initialStack, itemIcon, nextLine, onStack, reasonLine, stackView, FRESH_MS } from "../src/stack.ts";

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

test("each card says why it waits, in plain words (the Capsule design's wording)", () => {
  const now = 5 * 60_000;
  assert.equal(reasonLine(item("card:1", "waiting", "waiting"), now), "Waiting for your OK · behind another card");
  assert.equal(reasonLine(item("parked:a", "parked", "asked"), now), "Unanswered question · 5 min ago");
  assert.equal(reasonLine(item("parked:a", "parked", "stopped", now - 30_000), now), "Unfinished · stopped before it was done · just now");
  assert.equal(reasonLine(item("card:1", "held", "held"), now), "Waiting for your OK · held while you were away");
  assert.equal(reasonLine(item("card:1", "later", "expired", now - 120_000), now), "Waiting for your OK · held, no answer in time · 2 min ago");
  assert.equal(reasonLine(item("card:1", "later", "later", now - 60_000), now), "Waiting for your OK · put off 1 min ago");
  const view = stackView(onStack(initialStack, [item("parked:a"), item("card:1", "waiting", "waiting")], 0), 0)!;
  assert.deepEqual(view.items.map((i) => i.open), ["Open", "Open"]);
  assert.equal(countLine(1), "1 thing needs you");
  assert.equal(countLine(3), "3 things need you");
  assert.equal(nextLine(view), "Next: Title parked:a");
});

test("each row's icon says what kind of thing it is, beside its words", () => {
  assert.equal(itemIcon(item("card:1", "held", "held")), "shield");
  assert.equal(itemIcon(item("card:1", "later", "expired")), "shield");
  assert.equal(itemIcon(item("card:1", "waiting", "waiting")), "shield");
  assert.equal(itemIcon(item("parked:a", "parked", "asked")), "question");
  assert.equal(itemIcon(item("parked:a", "parked", "stopped")), "pause");
  assert.equal(itemIcon(item("parked:a", "parked", "unanswered")), "pause");
});

test("titles are passed whole: the view never cuts them (the owner's bug: truncated titles)", () => {
  const long = { ...item("card:9", "later", "later"), title: "Add lunch with Test Person at the Italian place on Thursday at one" };
  const view = stackView(onStack(initialStack, [long], 0), 0)!;
  assert.equal(view.items[0].title, long.title);
});

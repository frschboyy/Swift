import { test } from "node:test";
import assert from "node:assert/strict";
import { step } from "../src/keyed.ts";

test("Tab from the text box reaches the card's first button, then the next, then back to the text", () => {
  const keys = ["r1:approve", "r1:reject"];
  assert.equal(step(keys, null, 1), "r1:approve");
  assert.equal(step(keys, "r1:approve", 1), "r1:reject");
  assert.equal(step(keys, "r1:reject", 1), null);
  assert.equal(step(keys, null, -1), "r1:reject");
  assert.equal(step(keys, "r1:approve", -1), null);
});

test("a card with no buttons, or a button from another card, starts again from the text", () => {
  assert.equal(step([], null, 1), null);
  assert.equal(step([], "r1:approve", 1), null);
  // The card changed under the ring: the next card's Approve is reached afresh, never kept.
  assert.equal(step(["r2:approve", "r2:reject"], "r1:approve", 1), "r2:approve");
});

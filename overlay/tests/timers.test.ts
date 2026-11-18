import { strict as assert } from "node:assert";
import { test } from "node:test";
import { doneLine, left, pillText } from "../src/timers.ts";

const tea = { id: 7, title: "Tea", due_ms: 300_000, set_ms: 0 };

test("B14: the pill says m:ss of the soonest timer, '· N' with more than one (D6)", () => {
  assert.equal(pillText([], 0), "");
  assert.equal(pillText([tea], 48_000), "4:12");
  assert.equal(pillText([tea], 258_000), "0:42");
  assert.equal(pillText([tea, { ...tea, id: 8, due_ms: 900_000 }], 48_000), "4:12 · 2");
  assert.equal(pillText([tea], 400_000), "0:00");
});

test("the ring drains from full to empty over the timer's time", () => {
  assert.equal(left([tea], 0), 1);
  assert.equal(left([tea], 150_000), 0.5);
  assert.equal(left([tea], 400_000), 0);
  assert.equal(left([], 0), 0);
});

test("B14: Done on a timer's Due card says Edge · Got it in the timer's own name", () => {
  assert.equal(doneLine("Your tea timer is up."), "Done: Tea timer");
  assert.equal(doneLine("Your timer is up."), "Done: Timer");
});

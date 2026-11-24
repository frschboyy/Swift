import { strict as assert } from "node:assert";
import { test } from "node:test";
import { bump, nextChips, sayLines } from "../src/learn.ts";

const hints = {
  say: { confirm: [{ text: "approve", ok: false }], done: [{ text: "undo that", ok: false }] },
  verbs: [
    { learn: "copy", label: "Put it in Word", say: "put that in Word", ok: true },
    { learn: "show", label: "Show me again", say: "show me again", ok: false },
    { learn: "x", label: "Third", say: "third", ok: false },
  ],
};
const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

test("A10/A11: nothing is learned from 2 repeats; 3 Copy clicks make one hint and one chip", () => {
  const s = mem();
  bump(s, "copy"); bump(s, "copy");
  assert.deepEqual(sayLines("done", hints, s), hints.say.done);
  assert.deepEqual(nextChips(hints, s), []);
  bump(s, "copy");
  assert.deepEqual(sayLines("done", hints, s).at(-1), { text: "put that in Word", ok: true, learned: true });
  assert.deepEqual(nextChips(hints, s), [{ learn: "copy", label: "Put it in Word", say: "put that in Word", ok: true }]);
  assert.deepEqual(sayLines("confirm", hints, s), hints.say.confirm);  // a confirm card learns nothing
});

test("A11: at most 2 chips; a broken store learns nothing", () => {
  const s = mem();
  for (const a of ["copy", "show", "x"]) for (let i = 0; i < 3; i++) bump(s, a);
  assert.equal(nextChips(hints, s).length, 2);
  const broken = { getItem: () => { throw new Error("no"); }, setItem: () => { throw new Error("no"); } };
  bump(broken, "copy");
  assert.deepEqual(nextChips(hints, broken), []);
});

test("A11: a chip is offered only for what its own card can do (owner, 2026-11-18: Show me again on a time answer)", () => {
  const s = mem();
  for (const a of ["copy", "show"]) for (let i = 0; i < 3; i++) bump(s, a);
  const timeAnswer = (learn: string) => learn === "copy";  // copyable text, nothing to show
  assert.deepEqual(nextChips(hints, s, timeAnswer).map((c) => c.learn), ["copy"]);
  assert.deepEqual(nextChips(hints, s, () => false), []);
});

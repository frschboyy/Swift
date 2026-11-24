import { strict as assert } from "node:assert";
import { test } from "node:test";
import { bump, nextChips } from "../src/learn.ts";

const hints = {
  verbs: [
    { learn: "copy", label: "Put it in Word", say: "put that in Word", ok: true },
    { learn: "show", label: "Show me again", say: "show me again", ok: false },
    { learn: "x", label: "Third", say: "third", ok: false },
  ],
};
const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

test("A11: nothing is learned from 2 repeats; 3 Copy clicks make one chip", () => {
  const s = mem();
  bump(s, "copy"); bump(s, "copy");
  assert.deepEqual(nextChips(hints, s), []);
  bump(s, "copy");
  assert.deepEqual(nextChips(hints, s), [{ label: "Put it in Word", say: "put that in Word", ok: true }]);
});

test("A11: at most 2 chips; a broken store learns nothing", () => {
  const s = mem();
  for (const a of ["copy", "show", "x"]) for (let i = 0; i < 3; i++) bump(s, a);
  assert.equal(nextChips(hints, s).length, 2);
  const broken = { getItem: () => { throw new Error("no"); }, setItem: () => { throw new Error("no"); } };
  bump(broken, "copy");
  assert.deepEqual(nextChips(hints, broken), []);
});

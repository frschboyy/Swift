import { strict as assert } from "node:assert";
import { test } from "node:test";
import { choose, DEFAULTS, load, readingMs, save } from "../src/display.ts";

const memory = (): Pick<Storage, "getItem" | "setItem"> => {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
};

test("A8: the choices are kept, anything unknown keeps the default, and reading time scales or holds", () => {
  const store = memory();
  assert.deepEqual(load(store), DEFAULTS);
  let d = choose(DEFAULTS, "reading:1.5");
  d = choose(d, "text:large");
  d = choose(d, "motion:sideways");  // unknown: unchanged
  save(d, store);
  assert.deepEqual(load(store), { reading: "1.5", text: "large", motion: "windows" });
  assert.equal(readingMs(d, 6000), 9000);
  assert.equal(readingMs(choose(d, "reading:hold"), 6000), null);
  assert.deepEqual(load({ getItem: () => "{not json" }), DEFAULTS);
});

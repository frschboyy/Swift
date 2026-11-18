import { strict as assert } from "node:assert";
import { test } from "node:test";
import { choose, DEFAULTS, load, readingMs, save, watchOpens, LONG_RUN_MS } from "../src/display.ts";

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
  assert.deepEqual(load(store), { ...DEFAULTS, reading: "1.5", text: "large", motion: "windows" });
  assert.equal(readingMs(d, 6000), 9000);
  assert.equal(readingMs(choose(d, "reading:hold"), 6000), null);
  assert.deepEqual(load({ getItem: () => "{not json" }), DEFAULTS);
});

test("A8: speak answers and watch opens are kept, defaulting to config.yaml and to asking", () => {
  assert.equal(DEFAULTS.speak, "default");
  assert.equal(DEFAULTS.watch, "ask");
  assert.deepEqual(choose(DEFAULTS, "speak:never").speak, "never");
  assert.deepEqual(choose(DEFAULTS, "speak:loud"), DEFAULTS);
  const kept = new Map<string, string>();
  save({ ...DEFAULTS, watch: "writes" }, { setItem: (k, v) => kept.set(k, v) });
  assert.equal(load({ getItem: (k) => kept.get(k) ?? null }).watch, "writes");
});

test("A8: the watch opens by itself only as chosen, and never again once seen", () => {
  assert.equal(watchOpens(DEFAULTS, true, LONG_RUN_MS, false), false);  // "When I ask"
  assert.equal(watchOpens({ ...DEFAULTS, watch: "writes" }, true, 0, false), true);
  assert.equal(watchOpens({ ...DEFAULTS, watch: "writes" }, false, LONG_RUN_MS, false), false);
  assert.equal(watchOpens({ ...DEFAULTS, watch: "long" }, false, LONG_RUN_MS, false), true);
  assert.equal(watchOpens({ ...DEFAULTS, watch: "long" }, false, LONG_RUN_MS - 1, false), false);
  assert.equal(watchOpens({ ...DEFAULTS, watch: "long" }, true, LONG_RUN_MS, true), false);
});

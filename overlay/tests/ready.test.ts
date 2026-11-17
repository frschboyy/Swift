import { strict as assert } from "node:assert";
import { test } from "node:test";
import { endRun, saysReady, startRun } from "../src/ready.ts";

const memory = (): Pick<Storage, "getItem" | "setItem"> => {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
};

test("D10: 'Swift is ready' after a first start, an update or a crash, not on an ordinary start", () => {
  const store = memory();
  assert.equal(saysReady(startRun("0.2.0", store), "0.2.0"), true);   // first start
  endRun("0.2.0", store);
  assert.equal(saysReady(startRun("0.2.0", store), "0.2.0"), false);  // quit, started again
  assert.equal(saysReady(startRun("0.2.0", store), "0.2.0"), true);   // the last one never ended: a crash
  endRun("0.2.0", store);
  assert.equal(saysReady(startRun("0.3.0", store), "0.3.0"), true);   // updated
});

test("a storage that fails says ready, as before", () => {
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(saysReady(startRun("0.2.0", broken), "0.2.0"), true);
});

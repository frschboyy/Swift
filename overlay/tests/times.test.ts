import { strict as assert } from "node:assert";
import { test } from "node:test";
import { ago } from "../src/times.ts";

test("§8.2: Done and Failed say how long ago, never a clock time", () => {
  const t = 1_000_000_000;
  assert.equal(ago(t, t), "just now");
  assert.equal(ago(t, t + 59_000), "just now");
  assert.equal(ago(t, t + 60_000), "1 min ago");
  assert.equal(ago(t, t + 59 * 60_000), "59 min ago");
  assert.equal(ago(t, t + 60 * 60_000), "1 h ago");
  assert.equal(ago(t, t + 5 * 3_600_000 + 1), "5 h ago");
  assert.equal(ago(t + 5000, t), "just now");  // a clock that stepped back
});

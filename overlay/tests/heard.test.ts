// The "Listening…" pulse (heard.ts). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { HEARD_MS, heard, heardVisible } from "../src/heard.ts";

test("the pulse shows at once and fades by itself", () => {
  const h = heard(1000, "wake", "Listening…");
  assert.equal(heardVisible(h, "idle", 1000), true);
  assert.equal(heardVisible(h, "working", 1000 + HEARD_MS - 1), true);
  assert.equal(heardVisible(h, "working", 1000 + HEARD_MS), false);
  assert.equal(heardVisible(null, "idle", 1000), false);
});

test("it stays out of the way while the orb says listening or transcribing", () => {
  const h = heard(0, "ptt", "Listening…");
  assert.equal(heardVisible(h, "listening", 10), false);
  assert.equal(heardVisible(h, "transcribing", 10), false);
});

test("a request recorded behind another says so; no text falls back to Listening", () => {
  assert.equal(heard(0, "queued", "Got it. Listening for the next one…").text, "Got it. Listening for the next one…");
  assert.equal(heard(0, "wake", "").text, "Listening…");
});

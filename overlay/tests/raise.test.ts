// When the overlay raises itself (raise.ts). Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { wantsRaise } from "../src/raise.ts";

test("hearing its name, a card or an open question raises the overlay", () => {
  assert.equal(wantsRaise({ type: "heard", data: { source: "wake", text: "" } }), true);
  assert.equal(wantsRaise({ type: "confirm.request", data: { request_id: "r", run_id: "x", title: "t", detail: "", tool: "Edit" } }), true);
  assert.equal(wantsRaise({ type: "ask", data: { ask_id: "a", run_id: "x", open: true } as never }), true);
});

test("levels, steps and a closed question don't", () => {
  assert.equal(wantsRaise({ type: "level", data: { rms: 0.1 } }), false);
  assert.equal(wantsRaise({ type: "ask", data: { ask_id: "a", run_id: "x", open: false } as never }), false);
});

// The overlay <-> backend contract (seams audit 2026-11, layer A). Run: npm test.
// The examples come from tests/fixtures/protocol/frames.json (protocol.examples.ts, checked by tsc).
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { onAsk } from "../src/ask.ts";
import { TO_OVERLAY } from "../src/protocol.examples.ts";
import { decode, encode, PROTOCOL_VERSION } from "../src/protocol.ts";

const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const onMessage = main.slice(main.indexOf("function onMessage(msg: Inbound)"));

test("every message the backend sends has a case in onMessage", () => {
  const types = [...new Set(TO_OVERLAY.map((f) => f.type))];
  const missing = types.filter((t) => !onMessage.includes(`case "${t}":`));
  assert.deepEqual(missing, [], "a backend message type the overlay would ignore");
});

test("every example survives the overlay's decode", () => {
  for (const f of TO_OVERLAY) {
    const raw = JSON.stringify({ v: PROTOCOL_VERSION, type: f.type, ts: 1, data: f.data });
    assert.deepEqual(decode(raw), { type: f.type, data: f.data });
  }
  assert.equal(decode(JSON.stringify({ v: 2, type: "state", data: {} })), null);
  assert.ok(encode({ type: "cancel", data: {} }).includes('"type":"cancel"'));
});

test("every question example opens or closes a question", () => {
  for (const f of TO_OVERLAY) {
    if (f.type !== "ask") continue;
    const shown = onAsk(null, f.data, 1000);
    assert.equal(shown === null, !f.data.open, JSON.stringify(f.data));
  }
});

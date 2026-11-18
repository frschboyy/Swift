import { strict as assert } from "node:assert";
import { test } from "node:test";
import { glanceLines } from "../src/glance.ts";

const ok = { id: "card:1", kind: "later", title: "Send the email", reason: "expired", since_ms: 0, thread_id: "t" } as const;
const asked = { id: "parked:t2", kind: "parked", title: "Which day?", reason: "asked", since_ms: 0, thread_id: "t2" } as const;

test("A12: one quiet line when nothing waits; timers, then what waits, amber only for an OK", () => {
  assert.deepEqual(glanceLines([], [], 0), [{ text: "Nothing waiting, nothing running" }]);
  assert.deepEqual(glanceLines([{ id: 7, title: "Tea", due_ms: 252_000, set_ms: 0 }], [asked], 0),
    [{ text: "Tea · 4:12 left" }, { text: "1 waiting", warn: false }]);
  assert.deepEqual(glanceLines([], [asked, ok], 0), [{ text: "2 waiting · 1 needs your OK", warn: true }]);
});

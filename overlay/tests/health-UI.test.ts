// Health audit 2026-11-12 (UI group): tests that reproduce open findings. Marked todo, as in
// seams-audit.test.ts: they fail until fixed (the suite stays green); drop the todo with the fix.
// Run: node --test tests/health-UI.test.ts
import { strict as assert } from "node:assert";
import { test } from "node:test";

import type { StackEntry } from "../src/protocol.ts";
import { FRESH_MS, initialStack, onStack, stackView } from "../src/stack.ts";

const entry = (id: string): StackEntry =>
  ({ id, kind: "later", title: id, reason: "later", since_ms: 0 }) as unknown as StackEntry;

test("HA-UI-05: a card that just joined the stack keeps its glow when another joins a moment later", { todo: "HA-UI-05: open finding" }, () => {
  let s = onStack(initialStack, [entry("a")], 0);
  s = onStack(s, [entry("a"), entry("b")], 1000);  // b joins 1 s after a
  const v = stackView(s, 2000)!;                     // still inside a's FRESH_MS
  assert.ok(2000 < FRESH_MS);
  assert.deepEqual(v.items.filter((i) => i.fresh).map((i) => i.id), ["a", "b"], "a stopped glowing after 1 s");
});

// Health audit 2026-11-12 (UI group): tests that reproduce open findings. Marked todo, as in
// seams-audit.test.ts: they fail until fixed (the suite stays green); drop the todo with the fix.
// Run: node --test tests/health-UI.test.ts
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { grabsEscape } from "../src/capsule.ts";
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

// HA-UI-01 (answered 2026-11-18): Esc is taken from other apps only while Swift types into an app or a card waits.

test("HA-UI-01: a long background run doesn't take Esc from other apps", () => {
  const at = (o: Partial<Parameters<typeof grabsEscape>[0]>) =>
    grabsEscape({ stage: "idle", writing: false, speaking: false, folds: false, typing: false, ...o });
  assert.equal(at({ stage: "working" }), false);  // researching: Esc belongs to the app in front
  assert.equal(at({ stage: "working", writing: true }), true);  // Swift types into an app: Esc stops it (ADR-012)
  assert.equal(at({ stage: "confirm" }), true);  // a card waits
  assert.equal(at({ stage: "listening" }), true);  // the owner is talking to Swift
  assert.equal(at({ stage: "transcribing" }), true);
  assert.equal(at({ speaking: true }), true);  // Esc stops Swift talking
  assert.equal(at({ folds: true }), true);  // the open stack or an expanded card folds
  assert.equal(at({ stage: "confirm", typing: true }), false);  // the text box has it
});

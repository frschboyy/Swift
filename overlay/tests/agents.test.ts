// What Swift says about who did the work (agents.ts). FD-13 (owner, 2026-11-15): Swift speaks as itself, so a
// result's footer never names the provider. Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { activityLabel, byline, handoffLabel } from "../src/agents.ts";

const CLAUDE = { id: "claude_code", name: "Claude Code" };

test("a result's footer says Swift, whoever did the work", () => {
  for (const agent of [null, undefined, { id: "swift", name: "Swift" }, CLAUDE, { id: "mock", name: "Demo agent" }]) {
    assert.equal(byline(agent), "Swift");
  }
});

test("the working card never names the provider either", () => {
  for (const words of [activityLabel(CLAUDE, "thinking"), activityLabel(CLAUDE, "reading", true), handoffLabel(CLAUDE)]) {
    assert.ok(!/claude/i.test(words), words);
  }
});

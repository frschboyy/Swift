// What the overlay says when Swift's engine stopped (audit 2026-10, B-04). Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { describeBackendProblem } from "../src/engine.ts";

const PROBLEMS = [
  "the backend stopped unexpectedly",
  "could not start the backend (C:\\Swift\\.venv\\Scripts\\python.exe): not found",
  "the backend rejected the session token",
  "config stt.model: unknown model",
];

test("a stopped engine's card offers Restart Swift, never quitting", () => {
  for (const problem of PROBLEMS) {
    const p = describeBackendProblem(problem);
    assert.equal(p.restart, true, problem);
    assert.ok(!/quit/i.test(`${p.message} ${p.hint ?? ""}`), problem);
    assert.equal(p.detail, problem.startsWith("config ") ? problem.slice("config ".length) : problem);
  }
});

test("an engine that died says so", () => {
  const p = describeBackendProblem("the backend stopped unexpectedly");
  assert.equal(p.title, "Swift's engine stopped");
  assert.match(p.hint ?? "", /Restart Swift/);
});

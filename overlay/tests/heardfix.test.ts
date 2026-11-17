// Correcting what Swift heard (heardfix.ts). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { FIX_KINDS, canFlag, fixToSave, hintDue, hintShown } from "../src/heardfix.ts";

test("the flag shows only on heard words with a kept clip, never on Needs your OK", () => {
  assert.equal(canFlag("abc", "result"), true);
  assert.equal(canFlag("abc", "working"), true);
  assert.equal(canFlag("abc", "confirm"), false);
  assert.equal(canFlag(null, "result"), false);
});

test("nothing is saved when nothing changed; a kind alone is enough", () => {
  assert.equal(fixToSave("hey christy", " hey christy ", null), null);
  assert.equal(fixToSave("hey christy", "", "name"), null);
  assert.deepEqual(fixToSave("hey christy", "hey Swift", null), { said: "hey Swift", kind: "other" });
  assert.deepEqual(fixToSave("hey christy", "hey christy", "background"), { said: "hey christy", kind: "background" });
});

test("the hint shows three times, and never again once used", () => {
  let stored: string | null = null;
  let shown = 0;
  for (let i = 0; i < 6; i++) if (hintDue(stored)) { stored = hintShown(stored); shown++; }
  assert.equal(shown, 3);
  assert.equal(hintDue("used"), false);
  assert.equal(hintDue("1"), true);
});

test("the kinds are the backend's, in its order", () => {
  const py = readFileSync(new URL("../../src/swift/stt/recordings.py", import.meta.url), "utf-8");
  const kinds = /FIX_KINDS = \(([^)]*)\)/.exec(py)![1].match(/"(\w+)"/g)!.map((k) => k.slice(1, -1));
  assert.deepEqual(FIX_KINDS.map((k) => k.id), kinds);
});

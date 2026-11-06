// A pane's window size, pinned by what went wrong (owner, 2026-11-06). The harness measures it: fit_pane's arguments.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

test("a pane's window takes its layout size, never a size mid-animation", () => {
  const source = readFileSync(new URL("../src/pane.ts", import.meta.url), "utf8");
  const fit = source.match(/function fit\(\): void \{[\s\S]*?\n\}/)?.[0] ?? "";
  assert.ok(fit.includes("offsetWidth") && fit.includes("offsetHeight"), fit);
  assert.ok(!fit.includes("getBoundingClientRect"), "a transform in progress would size the window");
});

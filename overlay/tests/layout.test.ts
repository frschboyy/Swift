// Layout faults Node can't draw, pinned by what caused them. These showed only on the real screen
// (owner, 2026-11-06). The dev harness measures them: scrollWidth on .card-in, fit_pane's arguments.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");

test("a card's scroller never scrolls sideways, and spans the padding its children reach into", () => {
  const css = read("../src/styles.css");
  assert.match(css, /\.card-in \{\s*overflow-x: hidden;/);
  assert.match(css, /margin-inline: calc\(-1 \* var\(--pad-left\)\) calc\(-1 \* var\(--pad-right\)\);/);
  assert.match(css, /padding-inline: var\(--pad-left\) var\(--pad-right\);/);
});


// Layout faults Node can't draw, pinned by what caused them. These showed only on the real screen
// (owner, 2026-11-06). The dev harness measures them: scrollWidth on .card-in, fit_pane's arguments.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");

test("the capsule's slot is 44 px in every state, so the card above it never moves when it changes", () => {
  const css = read("../src/styles.css");
  assert.match(css, /\.capsule \{[^}]*height: 44px;/);
  assert.match(css, /--orb: 36px;/);
  assert.match(css, /\.capsule\[data-p="orb"\] \{[^}]*margin: 4px 0;/);
  assert.match(css, /#stage \.capsule\[data-p="idle"\] \{ width: 14px; height: 14px; margin: 15px; \}/);
});

test("a card's scroller never scrolls sideways, and spans the padding its children reach into", () => {
  const css = read("../src/styles.css");
  assert.match(css, /\.card-in \{\s*overflow-x: hidden;/);
  assert.match(css, /margin-inline: calc\(-1 \* var\(--pad-left\)\) calc\(-1 \* var\(--pad-right\)\);/);
  assert.match(css, /padding-inline: var\(--pad-left\) var\(--pad-right\);/);
});


test("item 10: pointing at a stack row never moves the rows below it (the actions fade in, their place kept)", () => {
  const css = read("../src/styles.css");
  const rule = css.match(/\n\.stack-actions \{([^}]*)\}/)![1];
  assert.doesNotMatch(rule, /display: none/);
  assert.match(rule, /grid-column: 3; grid-row: 2;/);
  assert.match(rule, /visibility: hidden; opacity: 0;/);
  assert.doesNotMatch(css, /\.stack-actions \{ display: flex; \}/);
  assert.match(css, /\.stack-open-btn \{ grid-column: 3; grid-row: 1;/);
});

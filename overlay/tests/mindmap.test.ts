// B4's mind map shape (docs/design/b4-adaptive-results.md): its words for Copy and screen readers, and its size,
// which Swift's backend chose (swift/shapes.py). Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { detailsText } from "../src/answer.ts";
import { needsReader } from "../src/panes.ts";
import type { MindMap } from "../src/protocol.ts";

const party: MindMap = {
  kind: "mindmap", root: "Party", by: "worker", size: "card",
  children: [{ label: "Games", children: [{ label: "Treasure hunt", children: [{ label: "Clues", children: [] }] }] }, { label: "Food", children: [] }],
};

test("a mind map copies as indented lines, one idea per line", () => {
  assert.equal(detailsText(party), "Party\n- Games\n  - Treasure hunt\n    - Clues\n- Food");
  assert.equal(detailsText({ ...party, title: "Ideas", text: "Keep it small." }), "Ideas\nParty\n- Games\n  - Treasure hunt\n    - Clues\n- Food\nKeep it small.");
});

test("Swift's size decides whether a mind map opens in full", () => {
  assert.equal(needsReader("Two branches.", party), false);
  assert.equal(needsReader("Two branches.", { ...party, size: "expanded" }), true);
});

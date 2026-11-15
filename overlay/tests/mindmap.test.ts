// B4's mind map shape (docs/design/b4-adaptive-results.md): its words for Copy and screen readers, and its size,
// which Swift's backend chose (swift/shapes.py). Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { cardIdeas, detailsText } from "../src/answer.ts";
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

test("the card's ideas are taken level by level, so every branch shows", () => {
  const leaf = (label: string) => ({ label, children: [] });
  // A big first branch (eight ideas) and three more: depth first, the card's twelve would hide the last branches.
  const big = { label: "Games", children: ["a", "b", "c", "d", "e", "f", "g", "h"].map(leaf) };
  const branches = [big, { label: "Food", children: [leaf("Pizza"), leaf("Cake")] }, { label: "Invites", children: [leaf("Class")] }, leaf("Music")];
  const kept = cardIdeas(branches, 12);
  assert.equal(kept.size, 12);
  for (const b of branches) assert.ok(kept.has(b), `${b.label} shows`);
  const labels = [...kept].map((i) => i.label);
  assert.deepEqual(labels.slice(4), ["a", "b", "c", "d", "e", "f", "g", "h"], "then the next level, in order");
  assert.equal(cardIdeas(branches, 100).size, 15, "a small map is whole");
  // Every kept idea's parent is kept, so the tree drawn from them has no gaps.
  const deep = [{ label: "1", children: [{ label: "1.1", children: [leaf("1.1.1")] }] }, leaf("2")];
  assert.deepEqual([...cardIdeas(deep, 3)].map((i) => i.label), ["1", "2", "1.1"]);
});

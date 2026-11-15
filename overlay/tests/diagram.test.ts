// B4's diagram shape (docs/design/b4-adaptive-results.md): its words for Copy, and its size, which Swift's backend
// chose (swift/shapes.py). Drawing it needs a DOM and Mermaid: the dev harness checks that. Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { DIAGRAM_MIN_LABEL_PX, detailsText, diagramFits, shape } from "../src/answer.ts";
import { needsReader } from "../src/panes.ts";
import type { Diagram } from "../src/protocol.ts";

const flow: Diagram = { kind: "diagram", title: "A request", source: "flowchart LR\n  A --> B", by: "worker", size: "card" };

test("a diagram copies as its title, its source and the words under it", () => {
  assert.equal(detailsText({ ...flow, text: "Most runs need no card." }), "A request\nflowchart LR\n  A --> B\nMost runs need no card.");
});

test("Swift's size decides whether a diagram opens in full", () => {
  assert.equal(needsReader("Two steps.", flow), false);
  assert.equal(needsReader("Two steps.", { ...flow, size: "expanded" }), true);
  assert.equal(shape("Two steps.", flow, false), "text");
});

test("a diagram shrinks into the card only while its labels stay readable", () => {
  // Sizes measured in the harness, 13 px labels, a 464 px card.
  assert.equal(diagramFits(553, 161, 13, 464), true, "four steps left to right: 10.9 px");
  assert.equal(diagramFits(796, 161, 13, 464), false, "six left to right: 7.6 px, too wide");
  assert.equal(diagramFits(343, 422, 13, 464), false, "six top down: shrunk to 260 px tall, 8 px");
  assert.equal(diagramFits(300, 120, 13, 464), true, "never grown past its own size");
  assert.equal(diagramFits(464 / (DIAGRAM_MIN_LABEL_PX / 13), 100, 13, 464), true, "exactly the floor fits");
  assert.equal(diagramFits(300, 120, 9, 464), false, "labels already under the floor");
});

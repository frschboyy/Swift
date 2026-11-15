// B4's diagram shape (docs/design/b4-adaptive-results.md): its words for Copy, and its size, which Swift's backend
// chose (swift/shapes.py). Drawing it needs a DOM and Mermaid: the dev harness checks that. Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { detailsText, shape } from "../src/answer.ts";
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

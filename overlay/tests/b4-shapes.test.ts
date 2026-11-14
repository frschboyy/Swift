// B4 prototype (overlay/dev/b4/shapes.ts): the boundary a worker's typed result crosses. Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { type Diagram, layers, parseShape } from "../dev/b4/shapes.ts";

test("a well-formed comparison passes, with its pick", () => {
  const s = parseShape({ shape: "compare", items: ["A", "B"], pick: 1, rows: [{ label: "Price", values: ["1", "2"] }] }, "x");
  assert.equal(s.shape, "compare");
  assert.equal(s.shape === "compare" && s.pick, 1);
});

test("anything malformed falls back to the plain text", () => {
  const bad = [
    null, "<svg onload=x>", { shape: "html", html: "<b>" },
    { shape: "compare", items: ["only one"], rows: [{ label: "a", values: ["1"] }] },
    { shape: "compare", items: ["A", "B"], rows: [{ label: "a", values: ["1"] }] },  // a row too short
    { shape: "compare", items: ["A", "B"], pick: 7, rows: [] },
    { shape: "diagram", nodes: [{ id: "a", label: "A" }], edges: [{ from: "a", to: "zz" }] },
    { shape: "diagram", nodes: [{ id: "a", label: "A" }, { id: "a", label: "B" }], edges: [] },
    { shape: "diagram", nodes: Array.from({ length: 17 }, (_, i) => ({ id: `n${i}`, label: "x" })), edges: [] },
  ];
  for (const raw of bad) assert.deepEqual(parseShape(raw, "words"), { shape: "text", text: "words" }, JSON.stringify(raw));
});

test("layers follow the longest path, and a cycle stops", () => {
  const d: Diagram = { shape: "diagram", nodes: ["a", "b", "c", "d"].map((id) => ({ id, label: id })),
    edges: [{ from: "a", to: "b" }, { from: "b", to: "c" }, { from: "a", to: "c" }, { from: "c", to: "d" }, { from: "d", to: "b" }] };
  const rank = layers(d);
  assert.equal(rank.get("a"), 0);
  assert.ok(rank.get("c")! > rank.get("b")!);
  for (const r of rank.values()) assert.ok(r < d.nodes.length);
});

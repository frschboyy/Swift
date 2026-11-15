// B4's compare shape (docs/design/b4-adaptive-results.md): its words for Copy and screen readers, and its size,
// which Swift's backend chose (swift/shapes.py). Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { detailsText, PICK, shape } from "../src/answer.ts";
import { needsReader } from "../src/panes.ts";
import type { Compare } from "../src/protocol.ts";

const laptops: Compare = {
  kind: "compare", title: "Laptops", items: ["Zenbook 14", "XPS 13"], by: "worker", size: "card", pick: 1,
  rows: [{ label: "Weight", values: ["1.2 kg", "1.3 kg"] }, { label: "Battery", values: ["15 h", "12 h"] }],
};

test("a comparison reads as rows, its pick named as the worker's", () => {
  assert.equal(detailsText(laptops), "Laptops\n\tZenbook 14\tXPS 13\nWeight\t1.2 kg\t1.3 kg\nBattery\t15 h\t12 h\nWorker's pick: XPS 13");
  assert.ok(!/claude/i.test(PICK), "never names the provider");
  assert.equal(detailsText({ ...laptops, pick: undefined, title: undefined, text: "Prices vary." }).split("\n").at(-1), "Prices vary.");
});

test("Swift's size decides whether it opens in full, never its row count here", () => {
  assert.equal(needsReader("Zenbook.", laptops), false);
  assert.equal(needsReader("Zenbook.", { ...laptops, size: "expanded" }), true);
  assert.equal(shape("Zenbook.", laptops, false), "text");  // never the one-line display
});

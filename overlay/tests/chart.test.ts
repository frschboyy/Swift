import { strict as assert } from "node:assert";
import { test } from "node:test";

import { detailsText } from "../src/answer.ts";
import { needsReader } from "../src/panes.ts";
import type { Chart } from "../src/protocol.ts";

const chart: Chart = {
  kind: "chart",
  title: "Quarterly sales",
  type: "bar",
  x: ["Q1", "Q2", "Q3"],
  series: [
    { name: "North", values: [12, 18, 15] },
    { name: "South", values: [9, 14, 17] },
  ],
  unit: "units",
  by: "worker",
  size: "card",
  text: "Totals are preliminary.",
};

test("a chart copies all categories and values as text, not SVG", () => {
  assert.equal(
    detailsText(chart),
    "Quarterly sales\nUnit: units\n\tNorth\tSouth\nQ1\t12\t9\nQ2\t18\t14\nQ3\t15\t17\nTotals are preliminary.",
  );
  assert.equal(needsReader("Quarterly sales", chart), false);
});

test("an expanded chart opens in the reader", () => {
  assert.equal(needsReader("Quarterly sales", { ...chart, size: "expanded" }), true);
});

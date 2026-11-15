import { strict as assert } from "node:assert";
import { test } from "node:test";

import { detailsText } from "../src/answer.ts";
import { needsReader } from "../src/panes.ts";
import type { Preview } from "../src/protocol.ts";

test("a document preview copies its excerpt, not its path or image data", () => {
  const preview: Preview = {
    kind: "preview",
    path: "C:\\Users\\owner\\Documents\\budget.xlsx",
    title: "budget.xlsx",
    file_type: "xlsx",
    thumbnail: null,
    pages: null,
    excerpt: "Three teams, April, 42",
    by: "swift",
    size: "expanded",
  };

  const text = detailsText(preview);

  assert.equal(text, "budget.xlsx\nXLSX\nThree teams, April, 42");
  assert.ok(!text.includes(preview.path));
  assert.ok(!text.includes("base64"));
  assert.equal(needsReader("The spreadsheet's opening rows.", preview), true);
});

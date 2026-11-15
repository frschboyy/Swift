import { strict as assert } from "node:assert";
import { test } from "node:test";

import { detailsText } from "../src/answer.ts";
import { needsReader } from "../src/panes.ts";
import type { Cards } from "../src/protocol.ts";

const cards: Cards = {
  kind: "cards",
  title: "Current projects",
  cards: [
    { title: "Website refresh", detail: "Update the homepage and simplify navigation.", meta: "Planning" },
    { title: "Data migration", detail: "Move the archive to the new storage service.", meta: "In progress" },
  ],
  by: "worker",
  size: "card",
  text: "The schedule is preliminary.",
};

test("project cards copy every title, detail and status as plain text", () => {
  assert.equal(
    detailsText(cards),
    "Current projects\n- Website refresh\n  Planning\n  Update the homepage and simplify navigation.\n"
      + "- Data migration\n  In progress\n  Move the archive to the new storage service.\nThe schedule is preliminary.",
  );
  assert.equal(needsReader("Two projects", cards), false);
});

test("an expanded project-card set opens in the reader", () => {
  assert.equal(needsReader("Five projects", { ...cards, size: "expanded" }), true);
});

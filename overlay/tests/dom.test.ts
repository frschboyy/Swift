// dom.ts helpers that need no browser. Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { keepScroll } from "../src/dom.ts";

test("a redraw keeps the open stack's scroll place (2026-11-18: it snapped back to the top)", () => {
  let list = { scrollTop: 240 };
  const root = { querySelector: () => list } as unknown as ParentNode;
  keepScroll(root, ".stack-list", () => { list = { scrollTop: 0 }; });  // replaceChildren: a new list, at the top
  assert.equal(list.scrollTop, 240);
  const empty = { querySelector: () => null } as unknown as ParentNode;
  keepScroll(empty, ".stack-list", () => {});  // nothing to keep: no error
});

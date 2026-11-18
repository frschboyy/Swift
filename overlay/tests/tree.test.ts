import { strict as assert } from "node:assert";
import { test } from "node:test";
import { middleCut, pathOf, startOpen, treeKey, visibleRows } from "../src/tree.ts";
import type { TreeEntry } from "../src/protocol.ts";

const PICS: TreeEntry[] = [
  { name: "2026", folder: true, found: true, entries: [{ name: "beach.jpg", found: true }, { name: "made-up.jpg", found: false }] },
  { name: "notes.txt", found: true },
];

test("B13: a row's path comes from Swift's verified root and the names, only for rows Swift found", () => {
  assert.equal(pathOf(PICS, "0/0", "C:\\Users\\F\\Pictures"), "C:\\Users\\F\\Pictures\\2026\\beach.jpg");
  assert.equal(pathOf(PICS, "0/1", "C:\\Users\\F\\Pictures"), null);  // not on disk
  assert.equal(pathOf(PICS, "1", undefined), null);  // no verified root: no actions at all
  assert.equal(pathOf(PICS, "9", "C:\\x"), null);
});

test("B13: arrow keys in the reader walk the rows and open and close folders", () => {
  let open = new Set<string>();
  let rows = visibleRows(PICS, open);
  let r = treeKey(rows, open, null, "ArrowDown");
  assert.equal(r.selected, "0");
  r = treeKey(rows, open, "0", "ArrowRight");  // opens the folder
  open = r.open;
  rows = visibleRows(PICS, open);
  assert.deepEqual([...open], ["0"]);
  r = treeKey(rows, open, "0", "ArrowRight");  // then steps into it
  assert.equal(r.selected, "0/0");
  r = treeKey(rows, open, "0/0", "ArrowLeft");  // out to its folder
  assert.equal(r.selected, "0");
  r = treeKey(rows, open, "0", "ArrowLeft");  // closes it
  assert.deepEqual([...r.open], []);
  assert.equal(treeKey(rows, open, "1", "ArrowDown").selected, "1");  // the last row stays
});

test("B13: a long name is cut in the middle and keeps its extension", () => {
  assert.equal(middleCut("notes.txt"), "notes.txt");
  const cut = middleCut("Quarterly report for the board, second draft with comments final.xlsx", 40);
  assert.equal(cut.length, 40);
  assert.ok(cut.endsWith("final.xlsx") && cut.startsWith("Quarterly report") && cut.includes("…"), cut);
  assert.equal(middleCut("a".repeat(60), 21), `${"a".repeat(10)}…${"a".repeat(10)}`);
});

test("folders start closed except the one that answers; an open folder shows its entries indented", () => {
  const entries = [
    { name: "2025", folder: true, entries: [{ name: "old.jpg" }] },
    { name: "2026", folder: true, open: true, entries: [{ name: "beach.jpg" }, { name: "trip", folder: true, entries: [{ name: "a.jpg" }] }] },
    { name: "notes.txt" },
  ];
  const open = new Set(startOpen(entries));
  assert.deepEqual([...open], ["1"]);
  assert.deepEqual(visibleRows(entries, open).map((r) => `${r.depth}:${r.entry.name}`), ["0:2025", "0:2026", "1:beach.jpg", "1:trip", "0:notes.txt"]);
});

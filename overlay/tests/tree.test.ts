import { strict as assert } from "node:assert";
import { test } from "node:test";
import { middleCut, startOpen, visibleRows } from "../src/tree.ts";

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

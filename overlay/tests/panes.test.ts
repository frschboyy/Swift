// The overlay's extra windows (ADR-015 §3). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  diffPanes, needsReader, openReader, paneLabel, queuedRows, readerTick, touchReader, wantedPanes, workingQuiet,
  READER_QUIET_MS, WORKING_QUIET_MS,
} from "../src/panes.ts";
import { initial, onRuns, MAX_ROWS, type Row } from "../src/presenter.ts";

const row = (runId: string, state = "working", title = runId): Row => ({
  runId, threadId: null, title, state, activity: null, app: null, startedMs: 0, summary: "",
});
const label = (r: Row) => `doing ${r.state}`;

test("each other running request gets its own window; the one in front doesn't", () => {
  const p = onRuns(initial, "a", [row("a"), row("b"), row("c", "confirm")], 0);
  const panes = wantedPanes(p, null, label);
  assert.deepEqual(panes.map((s) => s.label), ["pane-run-b", "pane-run-c"]);
  assert.deepEqual(panes.map((s) => s.index), [0, 1]);
  assert.equal(panes[1].view.kind === "request" && panes[1].view.label, "doing confirm");
});

test("a queued request is a line on the card, not a window", () => {
  const p = onRuns(initial, "a", [row("b"), row("q", "queued")], 0);
  assert.deepEqual(wantedPanes(p, null, label).map((s) => s.label), ["pane-run-b"]);
  assert.deepEqual(queuedRows(p).map((r) => r.runId), ["q"]);
});

test("never more request windows than the run limit", () => {
  const rows = ["b", "c", "d", "e", "f"].map((id) => row(id));
  const p = onRuns(initial, "a", rows, 0);
  assert.equal(wantedPanes(p, null, label).length, MAX_ROWS);
});

test("an ended request keeps its window until its row goes", () => {
  const p = onRuns(initial, "a", [row("b", "result")], 0);
  const [pane] = wantedPanes(p, null, label);
  assert.equal(pane.view.kind === "request" && pane.view.running, false);
  assert.deepEqual(wantedPanes(onRuns(p, "a", [], 0), null, label), []);
});

test("labels are safe window labels", () => {
  assert.equal(paneLabel("request", "req-ab.12 x"), "pane-run-req-ab_12_x");
  assert.equal(paneLabel("reader"), "pane-reader");
});

test("the reader opens on a long answer, and shrinks to a chip after a quiet minute", () => {
  let r = openReader("Research", "x".repeat(900), null, "a", 0);
  assert.equal(wantedPanes(initial, r, label)[0].label, "pane-reader");
  r = readerTick(r, READER_QUIET_MS - 1, false);
  assert.equal(r?.chip, false);
  r = readerTick(r, READER_QUIET_MS, false);
  assert.equal(r?.chip, true);
  r = touchReader(r, READER_QUIET_MS + 10);
  assert.equal(r?.chip, false);
  // Hovering keeps it open.
  r = readerTick(r, READER_QUIET_MS * 5, true);
  r = readerTick(r, READER_QUIET_MS * 5 + 1000, false);
  assert.equal(r?.chip, false);
});

test("a working card collapses after a quiet period, not while the pointer is on it", () => {
  assert.equal(workingQuiet(1000, 1000 + WORKING_QUIET_MS, false), true);
  assert.equal(workingQuiet(1000, 1000 + WORKING_QUIET_MS - 1, false), false);
  assert.equal(workingQuiet(1000, 1000 + WORKING_QUIET_MS * 2, true), false);
  assert.equal(workingQuiet(0, WORKING_QUIET_MS * 2, false), false);  // nothing yet
});

test("Read all for long answers and long tables only", () => {
  assert.equal(needsReader("short", null), false);
  assert.equal(needsReader("x".repeat(601), null), true);
  const table = (n: number) => ({ kind: "table" as const, columns: ["When", "What", "Where"], rows: Array.from({ length: n }, () => ["a", "b", "c"]) });
  assert.equal(needsReader("3 events", table(6)), false);
  assert.equal(needsReader("9 events", table(9)), true);
  assert.equal(needsReader("", { kind: "list", items: ["a", "b", "c", "d", "e", "f", "g"] }), true);
});

test("windows are created, updated only when what they show changes, and closed", () => {
  const p = onRuns(initial, "a", [row("b"), row("c")], 0);
  const wanted = wantedPanes(p, null, label);
  const first = diffPanes(new Map(), wanted);
  assert.deepEqual(first.create.map((s) => s.label), ["pane-run-b", "pane-run-c"]);
  const open = new Map(wanted.map((s) => [s.label, JSON.stringify(s.view)]));
  assert.deepEqual(diffPanes(open, wanted), { create: [], update: [], close: [] });
  const later = wantedPanes(onRuns(p, "a", [row("b", "confirm")], 0), null, label);
  const d = diffPanes(open, later);
  assert.deepEqual(d.update.map((s) => s.label), ["pane-run-b"]);
  assert.deepEqual(d.close, ["pane-run-c"]);
});

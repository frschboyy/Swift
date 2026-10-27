// The overlay's extra windows (ADR-015 §3). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  diffPanes, needsReader, newRows, openReader, paneLabel, queuedRows, readerTick, touchReader, wantedPanes, workingQuiet,
  PaneSync, CHIP_DELAY_MS, MAX_PANES, READER_QUIET_MS, WORKING_QUIET_MS, type PaneSpec,
} from "../src/panes.ts";
import { initialStack, onStack, stackView } from "../src/stack.ts";
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

test("bug 4: a request waiting for a slot gets a chip too, so the owner sees it registered", () => {
  const p = onRuns(initial, "a", [row("b"), row("q", "queued")], 0);
  assert.deepEqual(wantedPanes(p, null, label).map((s) => s.label), ["pane-run-b", "pane-run-q"]);
  assert.deepEqual(queuedRows(p).map((r) => r.runId), ["q"]);
});

test("never more request windows than MAX_PANES", () => {
  const rows = ["b", "c", "d", "e", "f", "g", "h"].map((id) => row(id));
  const p = onRuns(initial, "a", rows, 0);
  assert.equal(wantedPanes(p, null, label).length, MAX_PANES);
  assert.ok(MAX_PANES > MAX_ROWS);
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

// ---- bug 1 (2026-10-27): a chip can never outlive its request ---------------------------------

/** A shell whose windows take a while to open, like the real one. */
class SlowShell {
  open = new Set<string>();
  sent: string[] = [];
  private pending: (() => void)[] = [];
  host = {
    open: (spec: PaneSpec) => new Promise<void>((done) => this.pending.push(() => { this.open.add(spec.label); done(); })),
    close: (label: string) => void this.open.delete(label),  // closing one that isn't open yet does nothing
    send: (label: string) => void this.sent.push(label),
  };
  finishOpening(): void {
    this.pending.splice(0).forEach((f) => f());
  }
}

const tick = () => new Promise((r) => setTimeout(r, 0));

test("bug 1: a request that ends while its window is still opening doesn't leave the window behind", async () => {
  const shell = new SlowShell();
  let p = onRuns(initial, "a", [row("a"), row("local-1", "idle", "What time is it?")], 0);
  const sync = new PaneSync(shell.host, () => wantedPanes(p, null, label));
  const first = sync.sync();  // the beside request's chip starts opening...
  await tick();
  p = onRuns(p, "local-1", [row("a")], 0);  // ...and its answer, 0 ms later, takes the front
  void sync.sync();
  shell.finishOpening();
  await tick();
  shell.finishOpening();  // pane-run-a, wanted now, opens
  await first;
  assert.ok(!shell.open.has("pane-run-local-1"), "the chip outlived its request");
  assert.ok(!sync.shown.has("pane-run-local-1"));
  assert.ok(sync.shown.has("pane-run-a"));
});

test("windows Swift doesn't want are strays to close, but not while a sync is opening one", async () => {
  const shell = new SlowShell();
  const p = onRuns(initial, "a", [row("b")], 0);
  const sync = new PaneSync(shell.host, () => wantedPanes(p, null, label));
  const running = sync.sync();
  await tick();
  assert.deepEqual(sync.strays(["pane-run-b", "pane-run-old"]), []);
  shell.finishOpening();
  await running;
  assert.deepEqual(sync.strays(["pane-run-b", "pane-run-old"]), ["pane-run-old"]);
});

test("a window that can't open: no pane windows, and the caller is told", async () => {
  let told = 0;
  const p = onRuns(initial, "a", [row("b")], 0);
  const sync = new PaneSync({ open: () => Promise.reject(new Error("no")), close: () => {}, send: () => {} }, () => wantedPanes(p, null, label), () => told++);
  await sync.sync();
  assert.equal(sync.available, false);
  assert.equal(told, 1);
  assert.equal(sync.shown.size, 0);
});

// ---- bug 4: a request said beside another shows at once --------------------------------------

test("bug 4: a new request is announced at once; its window waits a moment (instant answers don't flash one)", () => {
  const young = { ...row("b"), startedMs: 10_000 };
  const p = onRuns(initial, "a", [young], 0);
  assert.deepEqual(newRows(new Set(), p.rows).map((r) => r.runId), ["b"]);
  assert.deepEqual(newRows(new Set(["b"]), p.rows), []);
  assert.deepEqual(newRows(new Set(), [row("c", "result")]), []);  // already over: nothing to announce
  assert.deepEqual(wantedPanes(p, null, label, { now: 10_000 + CHIP_DELAY_MS - 1 }), []);
  assert.deepEqual(wantedPanes(p, null, label, { now: 10_000 + CHIP_DELAY_MS }).map((s) => s.label), ["pane-run-b"]);
});

// ---- the stack and the text box are panes too ------------------------------------------------

test("the stack is a pane while something waits; the text box while it's open", () => {
  const items = [{ id: "card:1", kind: "waiting" as const, title: "Add lunch", reason: "waiting", since_ms: 0, thread_id: null }];
  const stack = stackView(onStack(initialStack, items, 0), 0);
  const typing = { kind: "type" as const, draft: "", follows: null };
  const specs = wantedPanes(initial, null, label, { stack, typing, now: 0 });
  assert.deepEqual(specs.map((s) => [s.label, s.kind]), [["pane-stack", "stack"], ["pane-type", "type"]]);
  assert.deepEqual(wantedPanes(initial, null, label, { stack: stackView(initialStack, 0) }), []);
});

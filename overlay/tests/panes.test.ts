// The overlay's extra windows (ADR-015 §3). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import type { LiveView } from "../src/live.ts";
import {
  diffPanes, needsReader, openReader, paneLabel, readerTick, touchReader, wantedPanes, workingQuiet,
  PaneSync, READER_QUIET_MS, WORKING_QUIET_MS, type PaneSpec,
} from "../src/panes.ts";
import { initialStack, onStack, stackView } from "../src/stack.ts";

const live = (runId: string, doing = "Reading"): LiveView => ({
  kind: "live", runId, title: runId, doing, activity: null, sources: [], notes: [], written: null, hint: null,
  running: true, ended: null, startedMs: 0,
});

test("labels are safe window labels", () => {
  assert.equal(paneLabel("live", "req-ab.12 x"), "pane-live-req-ab_12_x");
  assert.equal(paneLabel("reader"), "pane-reader");
});

test("ADR-018: another request has no window of its own", () => {
  const src = readFileSync(new URL("../src/panes.ts", import.meta.url), "utf8");
  assert.doesNotMatch(src, /"request"/);
  assert.deepEqual(wantedPanes(null), []);
});

test("the reader opens on a long answer, and shrinks to a chip after a quiet minute", () => {
  let r = openReader("Research", "x".repeat(900), null, "a", 0);
  assert.equal(wantedPanes(r)[0].label, "pane-reader");
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
  const wanted = wantedPanes(null, { live: [live("b"), live("c")] });
  const first = diffPanes(new Map(), wanted);
  assert.deepEqual(first.create.map((s) => s.label), ["pane-live-b", "pane-live-c"]);
  const open = new Map(wanted.map((s) => [s.label, JSON.stringify(s.view)]));
  assert.deepEqual(diffPanes(open, wanted), { create: [], update: [], close: [] });
  const d = diffPanes(open, wantedPanes(null, { live: [live("b", "Writing")] }));
  assert.deepEqual(d.update.map((s) => s.label), ["pane-live-b"]);
  assert.deepEqual(d.close, ["pane-live-c"]);
});

// ---- bug 1 (2026-10-27): a pane can never outlive what it shows -------------------------------

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

test("bug 1: what ends while its window is still opening doesn't leave the window behind", async () => {
  const shell = new SlowShell();
  let views = [live("short")];
  const sync = new PaneSync(shell.host, () => wantedPanes(null, { live: views }));
  const first = sync.sync();  // its window starts opening...
  await tick();
  views = [live("other")];  // ...and it ends, 0 ms later
  void sync.sync();
  shell.finishOpening();
  await tick();
  shell.finishOpening();  // pane-live-other, wanted now, opens
  await first;
  assert.ok(!shell.open.has("pane-live-short"), "the window outlived what it showed");
  assert.ok(!sync.shown.has("pane-live-short"));
  assert.ok(sync.shown.has("pane-live-other"));
});

test("windows Swift doesn't want are strays to close, but not while a sync is opening one", async () => {
  const shell = new SlowShell();
  const sync = new PaneSync(shell.host, () => wantedPanes(null, { live: [live("b")] }));
  const running = sync.sync();
  await tick();
  assert.deepEqual(sync.strays(["pane-live-b", "pane-run-old"]), []);
  shell.finishOpening();
  await running;
  // A request's window left by the version before the Deck is one of them.
  assert.deepEqual(sync.strays(["pane-live-b", "pane-run-old"]), ["pane-run-old"]);
});

test("a shell without pane windows: none, and the caller is told", async () => {
  let told = 0;
  const fail = () => Promise.reject(new Error("dev shim: unhandled command open_pane"));
  const sync = new PaneSync({ open: fail, close: () => {}, send: () => {} }, () => wantedPanes(null, { live: [live("b")] }), () => told++);
  await sync.sync();
  assert.equal(sync.available, false);
  assert.equal(told, 1);
  assert.equal(sync.shown.size, 0);
});

test("a window that can't open just now: pane windows stay on, and it opens on the next change (16b)", async () => {
  let told = 0;
  let opened = 0;
  let fail = true;
  const open = () => (fail ? Promise.reject(new Error("no monitor")) : Promise.resolve(void opened++));
  const sync = new PaneSync({ open, close: () => {}, send: () => {} }, () => wantedPanes(null, { live: [live("b")] }), () => told++);
  await sync.sync();
  assert.equal(sync.available, true);
  assert.equal(told, 0);
  assert.equal(sync.shown.size, 0);
  fail = false;
  await sync.sync();
  assert.equal(opened, 1);
  assert.equal(sync.shown.size, 1);
});

// ---- the stack and the text box are panes too ------------------------------------------------

test("the stack is a pane while something waits; the text box while it's open", () => {
  const items = [{ id: "card:1", kind: "waiting" as const, title: "Add lunch", reason: "waiting", since_ms: 0, thread_id: null }];
  const stack = stackView(onStack(initialStack, items, 0), 0);
  const typing = { kind: "type" as const, draft: "", follows: null };
  const specs = wantedPanes(null, { stack, typing });
  assert.deepEqual(specs.map((s) => [s.label, s.kind]), [["pane-stack", "stack"], ["pane-type", "type"]]);
  assert.deepEqual(wantedPanes(null, { stack: stackView(initialStack, 0) }), []);
});

// ---- ADR-017: the Capsule design's pane sizes, the text box's notice, the tray menu -----------

test("the text box grows a row for 'Typing can't approve', and the tray menu is a pane", async () => {
  const Pn = await import("../src/panes.ts");
  const type = (confirm: boolean) => ({ label: "pane-type", kind: "type" as const, index: 0, view: { kind: "type" as const, draft: "", follows: null, confirm } });
  assert.deepEqual(Pn.paneSize(type(false)), { w: 512, h: 52 });
  assert.deepEqual(Pn.paneSize(type(true)), { w: 512, h: 96 });
  const tray = { kind: "tray" as const, status: "Listening for “Hey Swift”", paused: false, anchor: "bottom-center", smart: true, typeKey: "ctrl+space" };
  const specs = Pn.wantedPanes(null, { tray });
  assert.deepEqual(specs.map((s) => s.label), ["pane-tray"]);
  assert.deepEqual(Pn.paneSize(specs[0]), { w: 280, h: 400 });
  assert.equal(Pn.WORKING_QUIET_MS, 12_000);
});

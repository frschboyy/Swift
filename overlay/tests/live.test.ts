// The live view of a running request (ADR-017 §7). Run: npm test.
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  close, doingLine, ended, initialLive, name, onItem, onRows, openRuns, plain, tick, touch, view, watch, webUrl,
  FORGET_MS, LINGER_MS, MAX_NOTES, MAX_OPEN, MAX_SOURCES, MAX_WRITTEN, type Live,
} from "../src/live.ts";
import { diffPanes, paneLabel, paneSize, wantedPanes } from "../src/panes.ts";
import { initial, type Row } from "../src/presenter.ts";

const T = 1_000_000;
const src = (url: string, state: "found" | "reading" | "read" | "failed" = "found", title = "") =>
  ({ kind: "source" as const, url, title, site: "", state });

function research(): Live {
  let l = onItem(initialLive, "cc-1", { kind: "doing", text: "Searching the web: history of tea", activity: "searching" }, T);
  l = onItem(l, "cc-1", src("https://www.britannica.com/topic/tea", "found", "Tea | Britannica"), T + 1);
  l = onItem(l, "cc-1", src("https://en.wikipedia.org/wiki/History_of_tea", "found", "History of tea"), T + 2);
  l = onItem(l, "cc-1", { kind: "note", text: "Tea was first drunk in Yunnan." }, T + 3);
  return l;
}

test("items arrive before the view opens, and it shows them when it does", () => {
  let l = research();
  assert.deepEqual(openRuns(l), []);
  l = watch(l, "cc-1", "Research the history of tea", "", T + 10);
  const [r] = openRuns(l);
  const v = view(r);
  assert.equal(v.doing, "Searching: history of tea");
  assert.equal(v.activity, "searching");
  assert.deepEqual(v.sources.map((s) => [s.site, s.title]), [["britannica.com", "Tea | Britannica"], ["en.wikipedia.org", "History of tea"]]);
  assert.deepEqual(v.notes, ["Tea was first drunk in Yunnan."]);
  assert.ok(v.running && v.ended === null);
});

test("a source is listed once: reading, then read; its title is kept; only web addresses", () => {
  let l = research();
  l = onItem(l, "cc-1", src("https://www.britannica.com/topic/tea", "reading"), T + 5);
  l = onItem(l, "cc-1", src("https://www.britannica.com/topic/tea", "read"), T + 6);
  l = onItem(l, "cc-1", src("https://www.britannica.com/topic/tea", "found"), T + 7);  // never goes back
  const s = view(l.runs[0]).sources[0];
  assert.deepEqual([s.state, s.title, l.runs[0].sources.length], ["read", "Tea | Britannica", 2]);
  for (const bad of ["javascript:alert(1)", "file:///C:/x", "https://a.example/ x"]) {
    assert.equal(onItem(l, "cc-1", src(bad), T).runs[0].sources.length, 2, bad);
  }
  assert.equal(webUrl("http://x.example/a"), "http://x.example/a");
});

test("limits: sources, notes and written text are capped", () => {
  let l = initialLive;
  for (let i = 0; i < MAX_SOURCES + 10; i++) l = onItem(l, "r", src(`https://s${i}.example/`), T);
  for (let i = 0; i < MAX_NOTES + 5; i++) l = onItem(l, "r", { kind: "note", text: `note ${i}` }, T);
  l = onItem(l, "r", { kind: "text", text: "x".repeat(MAX_WRITTEN + 500), app: "Word" }, T);
  const r = l.runs[0];
  assert.equal(r.sources.length, MAX_SOURCES);
  assert.equal(r.sources[0].url, "https://s10.example/");  // the newest kept
  assert.equal(r.notes.length, MAX_NOTES);
  assert.equal(r.written!.text.length, MAX_WRITTEN);
  // The same note twice in a row is one note.
  assert.equal(onItem(l, "r", { kind: "note", text: r.notes[r.notes.length - 1] }, T).runs[0].notes.length, MAX_NOTES);
});

test("research into Word: the text as it is written, paragraph by paragraph, and its app", () => {
  let l = watch(initialLive, "cc-2", "Research tea into Word", "", T);
  for (const p of ["The history of tea", "", "Tea began in China."]) l = onItem(l, "cc-2", { kind: "text", text: p, app: "Word" }, T);
  const v = view(l.runs[0]);
  assert.deepEqual(v.written, { app: "Word", text: "The history of tea\n\nTea began in China." });
  assert.match(plain(v), /Tea began in China/);
  l = onItem(l, "cc-2", { kind: "hint", text: "Here it is in Word." }, T);
  assert.equal(view(l.runs[0]).hint, "Here it is in Word.");
});

test("it ends with the answer linked, and closes by itself once nobody looks", () => {
  let l = watch(research(), "cc-1", "Tea", "", T);
  l = ended(l, "cc-1", "done", "Tea began in China.", { kind: "text", text: "More…" }, T + 1000);
  const v = view(l.runs[0]);
  assert.deepEqual([v.running, v.doing, v.ended?.answer, v.ended?.summary], [false, "Done", true, "Tea began in China."]);
  assert.equal(tick(l, T + 1000 + LINGER_MS - 1), l);  // still there
  // Looking at it holds it open.
  const held = tick(l, T + 1000 + LINGER_MS + 5, new Set(["cc-1"]));
  assert.equal(openRuns(held).length, 1);
  assert.equal(openRuns(tick(held, T + 1000 + 2 * LINGER_MS + 10)).length, 0);
  // Gone from memory a while later.
  const closed = tick(l, T + 1000 + LINGER_MS);
  assert.equal(openRuns(closed).length, 0);
  assert.equal(tick(closed, T + 1000 + FORGET_MS).runs.length, 0);
  // A running view never closes by itself.
  const running = watch(research(), "cc-1", "Tea", "", T);
  assert.equal(openRuns(tick(running, T + 10 * LINGER_MS)).length, 1);
});

test("a stopped or failed request says so, and offers no answer", () => {
  let l = watch(research(), "cc-1", "Tea", "", T);
  l = ended(l, "cc-1", "cancelled", "Cancelled.", null, T);
  assert.deepEqual([view(l.runs[0]).doing, view(l.runs[0]).ended?.answer], ["Stopped", false]);
  const failed = ended(watch(research(), "cc-1", "Tea", "", T), "cc-1", "error", "Couldn't reach the web", null, T);
  assert.equal(view(failed.runs[0]).doing, "Didn't finish");
});

test("a background request: title and end from its row", () => {
  const row: Row = { runId: "cc-1", threadId: null, title: "Tea history", state: "working", activity: "searching", app: null, startedMs: T, summary: "", words: "research the history of tea" };
  let l = onRows(research(), [row], T);
  assert.equal(l.runs[0].title, "Tea history");
  l = onRows(l, [{ ...row, state: "result", summary: "Tea began in China." }], T + 5);
  assert.deepEqual([l.runs[0].ended?.status, l.runs[0].ended?.summary], ["done", "Tea began in China."]);
  // The whole answer, when it comes, fills in the details; the end time stays.
  l = ended(l, "cc-1", "done", "Tea began in China.", { kind: "list", items: ["a"] }, T + 9);
  assert.deepEqual([l.runs[0].ended?.at, l.runs[0].ended?.details?.kind], [T + 5, "list"]);
  // A name never overwrites one already known; an unknown request isn't created by its row.
  assert.equal(name(l, "cc-1", "Other").runs[0].title, "Tea history");
  assert.equal(onRows(initialLive, [row], T).runs.length, 0);
});

test("one view per request, at most MAX_OPEN; the one looked at longest ago gives way", () => {
  let l = initialLive;
  for (let i = 1; i <= MAX_OPEN; i++) l = watch(l, `r${i}`, `R${i}`, "", T + i);
  l = touch(l, "r1", T + 100);
  l = watch(l, "r9", "R9", "", T + 200);
  assert.deepEqual(openRuns(l).map((r) => r.runId).sort(), ["r1", "r3", "r9"]);
  l = close(l, "r9");
  assert.deepEqual(openRuns(l).map((r) => r.runId).sort(), ["r1", "r3"]);
});

test("the view's words for what it does", () => {
  assert.equal(doingLine("Fetching britannica.com"), "Reading britannica.com");
  assert.equal(doingLine("Writing in Word"), "Writing in Word");
  assert.equal(view(onItem(initialLive, "x", { kind: "note", text: "n" }, T).runs[0]).doing, "Starting…");
});

test("each open live view is a pane window of its own, updated in place", () => {
  let l = watch(research(), "cc-1", "Tea", "", T);
  l = watch(l, "cc/2", "Notes", "", T);
  const specs = wantedPanes(null, { live: openRuns(l).map(view) });
  assert.deepEqual(specs.map((s) => [s.label, s.kind, s.index]), [["pane-live-cc-1", "live", 0], ["pane-live-cc_2", "live", 1]]);
  assert.equal(paneLabel("live", "cc-1"), "pane-live-cc-1");
  assert.deepEqual(paneSize(specs[0]), { w: 420, h: 480 });
  const shown = new Map(specs.map((s) => [s.label, JSON.stringify(s.view)]));
  const later = onItem(l, "cc-1", { kind: "note", text: "more" }, T);
  const d = diffPanes(shown, wantedPanes(null, { live: openRuns(later).map(view) }));
  assert.deepEqual([d.create.length, d.update.map((s) => s.label), d.close], [0, ["pane-live-cc-1"], []]);
  const gone = diffPanes(shown, wantedPanes(null, { live: openRuns(close(l, "cc-1")).map(view) }));
  assert.deepEqual(gone.close, ["pane-live-cc-1"]);
});

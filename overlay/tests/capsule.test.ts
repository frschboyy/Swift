// The Capsule design's pure parts (ADR-017): the capsule's state, how an answer reads, and the
// theme. Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import * as A from "../src/answer.ts";
import { pausedBy, presence, view, type CapsuleInput } from "../src/capsule.ts";
import { themeFrom } from "../src/theme.ts";

const at = (over: Partial<CapsuleInput>): CapsuleInput => ({ state: "idle", heard: false, quiet: false, speaking: false, paused: null, cardOpen: false, ...over });

// ---- the capsule ------------------------------------------------------------------------------

test("the owner talking comes first, then heard, speaking, paused, working, idle", () => {
  assert.equal(presence(at({ state: "listening", speaking: true, paused: "mic" })), "listening");
  assert.equal(presence(at({ state: "listening", quiet: true })), "cant-hear");
  assert.equal(presence(at({ state: "transcribing", heard: true })), "transcribing");
  assert.equal(presence(at({ heard: true, speaking: true })), "heard");
  assert.equal(presence(at({ speaking: true, paused: "mic", state: "working" })), "speaking");
  assert.equal(presence(at({ paused: "mic", state: "working" })), "paused-mic");
  assert.equal(presence(at({ paused: "locked" })), "paused-locked");
  assert.equal(presence(at({ paused: "asleep" })), "paused-locked");
  assert.equal(presence(at({ state: "working" })), "working");
  assert.equal(presence(at({ state: "result" })), "idle");
  assert.equal(presence(at({ state: "confirm" })), "idle");
});

test("ADR-018: a card open shrinks it to the orb, unless it has something the card can't say", () => {
  assert.equal(presence(at({ cardOpen: true, state: "working" })), "orb");
  assert.equal(presence(at({ cardOpen: true, state: "result" })), "orb");
  assert.equal(presence(at({ cardOpen: true, state: "confirm" })), "orb");
  assert.equal(presence(at({ cardOpen: true, state: "listening" })), "listening");
  assert.equal(presence(at({ cardOpen: true, state: "listening", quiet: true })), "cant-hear");
  assert.equal(presence(at({ cardOpen: true, state: "transcribing" })), "transcribing");
  assert.equal(presence(at({ cardOpen: true, heard: true })), "heard");
  assert.equal(presence(at({ cardOpen: true, speaking: true })), "speaking");
  // The privacy indicator never gives way to a card.
  assert.equal(presence(at({ cardOpen: true, paused: "mic" })), "paused-mic");
  assert.equal(presence(at({ cardOpen: true, paused: "locked" })), "paused-locked");
  assert.equal(presence(at({ cardOpen: true, paused: "asleep" })), "paused-locked");
  assert.deepEqual(view("orb", "", "", null), { label: "", sub: "", button: null, clickable: false });
});

test("paused only when listening is really off: by the owner, or a locked screen with wake listening", () => {
  assert.equal(pausedBy(null), null);
  assert.equal(pausedBy({ listening: false, wake: true, reason: "locked", paused: true }), "mic");
  assert.equal(pausedBy({ listening: false, wake: true, reason: "locked" }), "locked");
  assert.equal(pausedBy({ listening: false, wake: true, reason: "asleep" }), "asleep");
  assert.equal(pausedBy({ listening: true, wake: true, reason: "unlocked" }), null);
  // Push-to-talk only: the microphone is never open at rest, so nothing is "not listening".
  assert.equal(pausedBy({ listening: false, wake: false, reason: "locked" }), null);
});

test("each state says a word, and only speaking and mic-off are clickable", () => {
  assert.deepEqual(view("heard", "", "", null), { label: "Listening…", sub: "", button: null, clickable: false });
  assert.equal(view("listening", "what's on my", "", null).sub, "what's on my");
  assert.equal(view("cant-hear", "", "", null).sub, "I can't hear you. Check your microphone.");
  assert.deepEqual(view("working", "", "0:12", null), { label: "Working on it", sub: "0:12", button: null, clickable: false });
  assert.deepEqual(view("speaking", "", "", null), { label: "Speaking", sub: "", button: "stop", clickable: true });
  assert.deepEqual(view("paused-mic", "", "", "mic"), { label: "Not listening", sub: "Mic off", button: "resume", clickable: true });
  assert.deepEqual(view("paused-locked", "", "", "locked"), { label: "Not listening", sub: "Screen locked", button: null, clickable: false });
  assert.equal(view("paused-locked", "", "", "asleep").sub, "PC was asleep");
  assert.equal(view("idle", "", "", null).clickable, false);
  // Status never names the provider.
  for (const p of ["orb", "heard", "listening", "transcribing", "cant-hear", "working", "speaking", "paused-mic", "paused-locked", "idle"] as const) {
    const v = view(p, "", "", null);
    assert.doesNotMatch(`${v.label} ${v.sub}`, /claude|anthropic/i);
  }
});

// ---- answers ----------------------------------------------------------------------------------

test("one short line is display text; tables, long and longer text are not", () => {
  assert.equal(A.shape("It's 3:42 pm", null, false), "line");
  assert.equal(A.shape("Probably not. There's a 20% chance of a light shower around 4 pm, then it clears.", null, false), "text");
  assert.equal(A.shape("Line one\nline two", null, false), "text");
  assert.equal(A.shape("Three things on Thursday.", { kind: "table", columns: ["Time", "What"], rows: [["9:00", "Design review"]] }, false), "table");
  assert.equal(A.shape("x", null, true), "long");
});

test("paragraphs stay apart, lists are lists, marks are kept as marks (never HTML)", () => {
  const b = A.blocks("Tea began in **southwest China**.\n\nUnder the *Tang* it became `daily`.\n- one\n- two\nAfter.");
  assert.equal(b.length, 4);
  assert.deepEqual(b[0], { kind: "p", runs: [{ text: "Tea began in ", marks: [] }, { text: "southwest China", marks: ["b"] }, { text: ".", marks: [] }] });
  assert.deepEqual(b[1].kind === "p" && b[1].runs.map((r) => r.marks), [[], ["i"], [], ["code"], []]);
  assert.deepEqual(b[2], { kind: "ul", items: [[{ text: "one", marks: [] }], [{ text: "two", marks: [] }]] });
  assert.equal(b[3].kind, "p");
  // Something that looks like markup stays text.
  assert.deepEqual(A.blocks("<b>hi</b> 2*3"), [{ kind: "p", runs: [{ text: "<b>hi</b> 2*3", marks: [] }] }]);
  assert.equal(A.plainText("**Bold** and _it_"), "Bold and it");
});

test("reading time is clamp(4 s, words × 240 ms, 20 s)", () => {
  assert.equal(A.readingMs("It's 3:42 pm"), 4000);
  assert.equal(A.readingMs(Array(25).fill("word").join(" ")), 6000);
  assert.equal(A.readingMs(Array(500).fill("word").join(" ")), 20000);
  assert.equal(A.minutesToRead(Array(450).fill("word").join(" ")), "3 min read");
  assert.equal(A.minutesToRead("short"), "1 min read");
});

// ---- the theme --------------------------------------------------------------------------------

test("the theme follows Windows, then the webview, and a pinned one wins", () => {
  assert.equal(themeFrom({ windows: true }), "light");
  assert.equal(themeFrom({ windows: false, media: true }), "dark");
  assert.equal(themeFrom({ windows: null, media: true }), "light");
  assert.equal(themeFrom({}), "dark");
  assert.equal(themeFrom({ windows: false, override: "light" }), "light");
  assert.equal(themeFrom({ windows: true, override: "nonsense" }), "light");
});

// Swift's question during a request (ask.ts). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { type AskData, askButtons, askLeft, askPill, askVisible, onAsk } from "../src/ask.ts";

const opened = (over: Partial<AskData> = {}): AskData => ({
  ask_id: "q1", run_id: "r1", open: true, question: "Which Sam: Sam Lee or Sam Okoro?", kind: "choice",
  options: ["Sam Lee", "Sam Okoro"], thread_id: "t1", phase: "asking", seconds: 25, ...over,
});

test("asking first, then the answer window starts when Swift has said it", () => {
  const asking = onAsk(null, opened(), 1000)!;
  assert.equal(asking.phase, "asking");
  assert.equal(asking.until, null);
  assert.equal(askPill(asking, true), "Speaking… I'll listen when I'm done");
  const listening = onAsk(asking, { ask_id: "q1", run_id: "r1", open: true, phase: "listening", seconds: 25 }, 5000)!;
  assert.equal(listening.question, "Which Sam: Sam Lee or Sam Okoro?");  // kept from the first message
  assert.deepEqual(listening.options, ["Sam Lee", "Sam Okoro"]);
  assert.equal(askLeft(listening, 5000), 25);
  assert.equal(askLeft(listening, 30_001), 0);
  assert.equal(askPill(listening, false), "Waiting for your answer");
});

test("once more shows the re-ask; heard stops the clock", () => {
  const first = onAsk(null, opened({ phase: "listening" }), 0)!;
  const again = onAsk(first, opened({ phase: "again", text: "Sorry, which one: Sam Lee or Sam Okoro?" }), 1000)!;
  assert.equal(again.question, "Sorry, which one: Sam Lee or Sam Okoro?");
  assert.equal(askPill(again, false), "Once more: waiting for your answer");
  const heard = onAsk(again, { ask_id: "q1", run_id: "r1", open: true, phase: "heard", seconds: 0 }, 2000)!;
  assert.equal(heard.until, null);
  assert.equal(askPill(heard, false), "Got it…");
});

test("closed only by its own id", () => {
  const a = onAsk(null, opened(), 0);
  assert.equal(onAsk(a, { ask_id: "other", run_id: "r1", open: false }, 1), a);
  assert.equal(onAsk(a, { ask_id: "q1", run_id: "r1", open: false }, 1), null);
  assert.equal(onAsk(null, { ask_id: "q1", run_id: "r1", open: false }, 1), null);
});

test("buttons for yes/no and short choices only", () => {
  assert.deepEqual(askButtons(onAsk(null, opened({ kind: "yes_no", options: [] }), 0)!), ["Yes", "No"]);
  assert.deepEqual(askButtons(onAsk(null, opened(), 0)!), ["Sam Lee", "Sam Okoro"]);
  assert.deepEqual(askButtons(onAsk(null, opened({ options: ["a", "b", "c", "d", "e"] }), 0)!), []);
  assert.deepEqual(askButtons(onAsk(null, opened({ kind: "free", options: [] }), 0)!), []);
  assert.deepEqual(askButtons(onAsk(null, opened({ kind: "duration", options: [] }), 0)!), []);
});

test("shown on its own request's working card only", () => {
  const a = onAsk(null, opened(), 0);
  assert.equal(askVisible(a, "working", "r1"), true);
  assert.equal(askVisible(a, "working", null), true);
  assert.equal(askVisible(a, "working", "r2"), false);  // another request in front: it waits
  assert.equal(askVisible(a, "confirm", "r1"), false);  // a confirm card hears "Swift, yes" first
  assert.equal(askVisible(null, "working", "r1"), false);
});

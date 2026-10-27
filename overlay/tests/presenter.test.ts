// Sequence tests for the presenter (ADR-013 §6). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  confirmVisible, initial, isActive, onAnswer, onConfirm, onConfirmHold, onDismiss, onFollowup, onHold, onRuns, onState,
  promotion, seenCard, tick, visibleRows, violations, waitingSince, MAX_ROWS, RESUME_MS,
  type Presenter, type Row,
} from "../src/presenter.ts";

/** Steps through a sequence, checking the invariants after every step. */
class Overlay {
  p: Presenter = initial;
  now = 0;
  hidden = 0;
  log: string[] = [];

  private check(step: string): void {
    this.log.push(step);
    assert.deepEqual(violations(this.p), [], `after ${this.log.join(" → ")}`);
  }

  state(state: Parameters<typeof onState>[1], run: string | null = null, thread: string | null = null) {
    const r = onState(this.p, state, run, thread);
    this.p = r.p;
    if (r.hide) this.hidden++;
    this.check(`state ${state}`);
    return r;
  }

  confirm(id: string, run: string) {
    this.p = onConfirm(this.p, id, run);
    this.check(`confirm ${id}`);
  }

  answer(kind: "result" | "error" | "notice", ms: number | null, run?: string, thread?: string, summary?: string) {
    const r = onAnswer(this.p, { kind, runId: run, threadId: thread, summary, ms }, this.now);
    this.p = r.p;
    this.check(`${kind}`);
    return r.shown;
  }

  runs(focus: string | null, rows: Row[], waiting = 0) {
    this.p = onRuns(this.p, focus, rows, waiting);
    this.check(`runs ${focus} +${rows.length}`);
  }

  followup(open: boolean, seconds = 8) {
    this.p = onFollowup(this.p, open, seconds, this.now);
    this.check(`followup ${open}`);
  }

  wait(ms: number) {
    for (let t = 0; t < ms; t += 250) {
      this.now += 250;
      const r = tick(this.p, this.now);
      this.p = r.p;
      if (r.hide) this.hidden++;
      this.check(`tick ${this.now}`);
    }
  }
}

test("the 2026-10-26 bug: a correction's confirm card is never hidden by the last answer's fade", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.confirm("swift:1", "cc-1");
  o.state("working", "cc-1", "t1"); // rejected: the provider wraps up
  o.state("result", "cc-1", "t1");
  o.answer("result", 6000, "cc-1", "t1", "Not added: Meeting, Thu 15:00");
  o.followup(true, 8);
  o.wait(2500); // the owner says the correction within the window
  o.followup(false);
  const started = o.state("working", "cc-2", "t1"); // no "listening": a follow-up
  assert.ok(started.newRun && started.continued);
  o.wait(1500);
  o.state("confirm", "cc-2", "t1");
  o.confirm("swift:2", "cc-2");
  o.wait(15000); // far past any fade the first answer had
  assert.equal(o.p.card.kind, "confirm");
  assert.equal(o.hidden, 0);
  assert.deepEqual(o.p.history, [{ threadId: "t1", text: "Not added: Meeting, Thu 15:00" }]);
});

test("an answer fades after its time, and only then", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.state("result", "cc-1", "t1");
  o.answer("result", 6000, "cc-1", "t1", "Done.");
  o.wait(5750);
  assert.equal(o.p.card.kind, "result");
  o.wait(500);
  assert.equal(o.p.card.kind, "none");
  assert.equal(o.hidden, 1);
});

test("hover holds an answer; letting go gives it RESUME_MS", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.answer("result", 6000, "cc-1", "t1");
  o.wait(5000);
  o.p = onHold(o.p, true, o.now);
  o.wait(20000);
  assert.equal(o.p.card.kind, "result");
  o.p = onHold(o.p, false, o.now);
  o.wait(RESUME_MS - 250);
  assert.equal(o.p.card.kind, "result");
  o.wait(500);
  assert.equal(o.p.card.kind, "none");
});

test("check 26: letting go of a question never shortens its reply window", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.answer("result", 6000, "cc-1", "t1");
  o.followup(true, 25);  // "Which day, and what time?": Swift listens 25 s
  o.wait(3000);
  o.p = onHold(o.p, true, o.now);  // the pointer passes over the card...
  o.wait(1000);
  o.p = onHold(o.p, false, o.now);  // ...and leaves: before, 2.5 s more, then gone
  o.wait(RESUME_MS + 1000);
  assert.equal(o.p.card.kind, "result");
  o.wait(25000 - 4000 - RESUME_MS - 1000 - 250);
  assert.equal(o.p.card.kind, "result");
  o.wait(1500);
  assert.equal(o.p.card.kind, "none");
});

test("the answer stays while the follow-up window is open", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.answer("result", 2000, "cc-1", "t1");
  o.followup(true, 8);
  o.wait(7000);
  assert.equal(o.p.card.kind, "result");
  o.wait(2000);
  assert.equal(o.p.card.kind, "none");
  assert.equal(o.p.followupUntil, 0);
});

test("offer → yes continues the thread; a new request starts a new one", () => {
  const o = new Overlay();
  o.state("listening");
  o.state("transcribing");
  o.state("result", "local-1", "t1");
  o.answer("result", 8000, "local-1", "t1", "I have a workflow for that: Add a calendar event.");
  const yes = o.state("working", "cc-1", "t1"); // "yes" in the follow-up window
  assert.ok(yes.newRun && yes.continued);
  assert.equal(o.p.history.length, 1);
  o.answer("result", 6000, "cc-1", "t1", "Added Lunch, Fri 12:00.");
  const other = o.state("working", "cc-2", "t2"); // "hey Swift, what's the weather"
  assert.ok(other.newRun && !other.continued);
  assert.deepEqual(o.p.history, []);
});

test("a thread shows at most its last two answers", () => {
  const o = new Overlay();
  for (const [i, run] of ["cc-1", "cc-2", "cc-3", "cc-4"].entries()) {
    o.state("working", run, "t1");
    o.answer("result", 6000, run, "t1", `answer ${i + 1}`);
  }
  o.state("working", "cc-5", "t1");
  assert.deepEqual(o.p.history.map((t) => t.text), ["answer 3", "answer 4"]);
});

test("Swift's notices never cover a request", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  assert.equal(o.answer("notice", 4000), false);
  assert.equal(o.p.card.kind, "working");
  o.answer("result", 6000, "cc-1", "t1");
  assert.equal(o.answer("notice", 4000), true); // the answer can be replaced by a notice
});

test("a late answer from an older request doesn't take over", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.answer("result", 1000, "cc-1", "t1");
  o.state("working", "cc-2", "t2");
  assert.equal(o.answer("result", 6000, "cc-1", "t1"), false); // e.g. a cancelled run's last word
  assert.equal(o.p.card.kind, "working");
  assert.equal(o.p.runId, "cc-2");
});

test("dismiss closes an answer, never a request", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  assert.equal(onDismiss(o.p).hide, false);
  o.answer("result", 6000, "cc-1", "t1");
  assert.equal(onDismiss(o.p).hide, true);
});

test("errors can stay until dismissed", () => {
  const o = new Overlay();
  o.answer("error", null); // e.g. "push-to-talk isn't working"
  o.wait(60000);
  assert.equal(o.p.card.kind, "error");
});

test("a reconnect mid-request ends it cleanly", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.confirm("swift:1", "cc-1");
  o.state("idle"); // the connection came back: the backend's run is gone
  assert.equal(o.p.card.kind, "none");
  assert.equal(o.p.pendingConfirm, null);
  assert.ok(!isActive(o.p));
});

test("the invariants catch a hidden waiting card", () => {
  const broken: Presenter = { ...initial, pendingConfirm: "swift:1", card: { ...initial.card, kind: "result" } };
  assert.match(violations(broken).join(), /waiting but not on screen/);
});

test("ADR-014 §4: a card put aside while the owner is away waits, then comes back; answering clears it", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.state("confirm", "cc-1", "t1");
  o.confirm("swift:1", "cc-1");
  o.p = onConfirmHold(o.p, "swift:1", true);
  assert.deepEqual(violations(o.p), []);
  assert.equal(confirmVisible(o.p), false);
  o.now += 12 * 3600 * 1000;
  const r = tick(o.p, o.now);
  assert.equal(r.hide, false);  // never faded while waiting
  assert.equal(r.p.pendingConfirm, "swift:1");
  o.p = onConfirmHold(o.p, "swift:2", false);  // another card's news changes nothing
  assert.equal(o.p.held, "swift:1");
  o.p = onConfirmHold(o.p, "swift:1", false);
  assert.equal(confirmVisible(o.p), true);
  o.p = onConfirmHold(o.p, "swift:1", true);
  o.answer("result", 4000, "cc-1", "t1", "Added: Meeting");
  assert.equal(o.p.held, null);
});


test("owner check 14: held, then back: the card is on screen with a fresh deadline and says it waited", () => {
  const o = new Overlay();
  o.now = 1_000_000;
  o.state("working", "cc-25", "t1");
  o.state("confirm", "cc-25", "t1");
  o.p = onConfirm(o.p, "swift:1", "cc-25", 120, o.now);
  assert.equal(o.p.confirmDeadline, o.now + 120_000);
  assert.equal(waitingSince(o.p), null);  // never put aside: no "waiting" line
  o.now += 12_000;
  const lockedAt = o.now;
  o.p = onConfirmHold(o.p, "swift:1", true, 108, o.now);  // locked
  assert.deepEqual(violations(o.p), []);
  assert.equal(confirmVisible(o.p), false);
  assert.equal(o.p.confirmDeadline, 0);  // no countdown while put aside
  o.now += 2_000;
  o.p = onConfirmHold(o.p, "swift:1", false, 108, o.now);  // unlocked: the backend gives it its time back
  assert.deepEqual(violations(o.p), []);
  assert.equal(confirmVisible(o.p), true);
  assert.equal(o.p.card.kind, "confirm");
  assert.equal(o.p.confirmDeadline, o.now + 108_000);  // fresh, from now
  assert.equal(waitingSince(o.p), lockedAt);  // "1 card waiting, since …"
  assert.equal(tick(o.p, o.now + 60_000).hide, false);
  // Drawn again (a new draft version): the same card keeps its deadline and its line.
  const again = onConfirm(o.p, "swift:1", "cc-25", 120, o.now + 5_000);
  assert.equal(again.confirmDeadline, o.now + 108_000);
  assert.equal(waitingSince(again), lockedAt);
  // Locked twice: "since" is the first time.
  o.p = onConfirmHold(o.p, "swift:1", true, 100, o.now + 10_000);
  o.p = onConfirmHold(o.p, "swift:1", false, 100, o.now + 20_000);
  assert.equal(waitingSince(o.p), lockedAt);
  // Answered: nothing waits any more.
  o.answer("result", 4000, "cc-25", "t1", "Added: Lunch");
  assert.equal(o.p.heldSince, null);
  assert.equal(o.p.confirmDeadline, 0);
  // The next card starts clean.
  o.state("confirm", "cc-26", "t2");
  o.p = onConfirm(o.p, "swift:2", "cc-26", 120, o.now);
  assert.equal(waitingSince(o.p), null);
});

// ---- several requests at once (ADR-013 phase B) -------------------------------------------

const row = (runId: string, state = "working", title = runId): Row => ({
  runId, threadId: `t-${runId}`, title, state, activity: "reading", app: null, startedMs: 0, summary: "",
});

test("phase B: two requests side by side; the background one never touches the card", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.runs("local-1", [row("cc-1")]); // "what time is it" while the research runs
  o.state("result", "local-1", "t2");
  assert.equal(o.answer("result", 6000, "local-1", "t2", "It's 10:42."), true);
  const late = o.state("working", "cc-1", "t1"); // the research's news: its row, not the card
  assert.ok(late.ignored);
  assert.equal(o.answer("result", 6000, "cc-1", "t1", "Tea came from China."), false);
  assert.equal(o.p.card.runId, "local-1");
  assert.deepEqual(visibleRows(o.p).rows.map((r) => r.runId), ["cc-1"]);
});

test("phase B: when the card in front fades, the running row comes forward", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.runs("local-1", [row("cc-1")]);
  o.answer("result", 2000, "local-1", "t2", "It's 10:42.");
  assert.equal(promotion(o.p), null); // the answer is still up
  o.wait(2250);
  assert.equal(o.p.card.kind, "none");
  assert.equal(promotion(o.p), "cc-1");
  o.runs("cc-1", []); // the backend brings it forward and draws its card again
  const back = o.state("working", "cc-1", "t1");
  assert.ok(back.newRun && !back.ignored);
  assert.equal(o.p.card.runId, "cc-1");
});

test("phase B: a card from the background waits behind the card on screen", () => {
  const o = new Overlay();
  o.state("working", "cc-2", "t2");
  o.runs("cc-1", [row("cc-2")]); // cc-1's card comes to the front
  o.state("working", "cc-1", "t1");
  o.state("confirm", "cc-1", "t1");
  o.confirm("cc-1:1", "cc-1");
  o.runs("cc-1", [row("cc-2", "confirm")], 1); // cc-2 asked too: it waits, counted on the card
  assert.equal(o.p.waiting, 1);
  o.state("confirm", "cc-2", "t2"); // a stray state from the waiting one changes nothing
  assert.equal(o.p.pendingConfirm, "cc-1:1");
  o.runs("cc-2", [row("cc-1")], 0); // answered: the next card comes forward
  assert.equal(o.p.pendingConfirm, null);
  o.state("confirm", "cc-2", "t2");
  o.confirm("cc-2:1", "cc-2");
  assert.equal(o.p.card.runId, "cc-2");
  assert.ok(confirmVisible(o.p));
});

test("phase B: naming a request brings its card forward", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.runs("cc-2", [row("cc-1", "working", "research the history of tea")]);
  o.state("working", "cc-2", "t2");
  o.runs("cc-1", [row("cc-2", "working", "summarise my notes")]); // "show me the research one"
  assert.equal(o.p.card.kind, "none");
  const shown = o.state("working", "cc-1", "t1");
  assert.ok(shown.newRun && !shown.continued);
  assert.equal(o.p.card.runId, "cc-1");
});

test("phase B: at most three rows, and the rest counted", () => {
  const o = new Overlay();
  o.state("working", "cc-9", "t9");
  o.runs("cc-9", ["cc-1", "cc-2", "cc-3", "cc-4", "cc-5"].map((r) => row(r)));
  const v = visibleRows(o.p);
  assert.equal(v.rows.length, MAX_ROWS);
  assert.equal(v.more, 2);
});

test("phase B: one request's row never repeats the one in front", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.runs("cc-1", [row("cc-1"), row("cc-2")]);
  assert.deepEqual(o.p.rows.map((r) => r.runId), ["cc-2"]);
});

test("phase B: the invariants catch two cards fighting and a waiting card off screen", () => {
  const fighting: Presenter = {
    ...initial, focus: "cc-2", rows: [row("cc-1")], card: { kind: "working", runId: "cc-1", threadId: "t1", fadeAt: null },
  };
  assert.match(violations(fighting).join(), /isn't the request in front/);
  const lost: Presenter = { ...initial, waiting: 1, card: { ...initial.card, kind: "working" } };
  assert.match(violations(lost).join(), /wait but none is on screen/);
  const twice: Presenter = { ...initial, focus: "cc-3", rows: [row("cc-1"), row("cc-1")] };
  assert.match(violations(twice).join(), /two rows/);
});

test("phase B: without rows, a single request behaves exactly as before", () => {
  const o = new Overlay();
  o.state("working", "cc-1", "t1");
  o.runs("cc-1", []);
  o.answer("result", 1000, "cc-1", "t1");
  const next = o.state("working", "cc-2", "t2"); // a new request, no runs message needed
  assert.ok(next.newRun && !next.ignored);
});

// ---- ADR-015: a card counts down only while it is seen ------------------------------------------

test("the card the owner can see: shown, put aside while away, back, answered", () => {
  const o = new Overlay();
  o.state("working", "r1", "t1");
  o.confirm("c1", "r1");
  assert.equal(seenCard(o.p), "c1");
  o.p = onConfirmHold(o.p, "c1", true, 0, 1000);
  assert.equal(seenCard(o.p), null);
  o.p = onConfirmHold(o.p, "c1", false, 60, 3000);
  assert.equal(seenCard(o.p), "c1");
  o.answer("result", 6000, "r1", "t1", "Not added");
  assert.equal(seenCard(o.p), null);
});

test("owner check 18: back after the overlay lost the card still draws it, because the backend replays it", () => {
  const o = new Overlay();
  o.state("working", "r1", "t1");
  o.confirm("c1", "r1");
  o.p = onConfirmHold(o.p, "c1", true, 0, 1000);
  // While it was hidden, another request came to the front and went again: the overlay forgot the card.
  o.runs("r2", [row("r1", "confirm")]);
  assert.equal(o.p.pendingConfirm, null);
  // Back: the backend draws the card again first (state, card), then says how long it has.
  o.runs("r1", []);
  o.state("confirm", "r1", "t1");
  o.confirm("c1", "r1");
  o.p = onConfirmHold(o.p, "c1", false, 60, 3000);
  assert.equal(seenCard(o.p), "c1");
  assert.equal(o.p.confirmDeadline, 3000 + 60_000);
});

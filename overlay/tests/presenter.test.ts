// Sequence tests for the presenter (ADR-013 §6). Run: npm test (node --test, no extra packages).
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  confirmVisible, initial, isActive, onAnswer, onConfirm, onConfirmHold, onDismiss, onFollowup, onHold, onState, tick,
  violations, RESUME_MS,
  type Presenter,
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


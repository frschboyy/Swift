// Seams audit 2026-11 (overlay and IPC): tests that reproduce open findings (docs/audit/2026-11-seams-audit.md). Marked todo: they fail until fixed.
// Run: node --test tests/seams-audit.test.ts
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { PaneSync, type PaneSpec } from "../src/panes.ts";
import { initial, onAnswer, onConfirm, onState } from "../src/presenter.ts";

const typeBox: PaneSpec = { label: "pane-type", kind: "type", index: 0, view: { kind: "type", draft: "", follows: null, confirm: true } };

test("O-03: a text box whose window failed to open once is opened again without another change", { todo: "seams audit O-03: open finding; drop todo with the fix" }, async () => {
  // #4 / #16b: Change (or the hotkey) asks for the text box; the window fails once (no monitor under
  // the cursor, a busy shell). main.ts keeps `typing` set, so a second Change does nothing and a
  // second hotkey press *closes* it. Nothing retries until some unrelated change (Reject) syncs again.
  let calls = 0;
  const opened: string[] = [];
  const sync = new PaneSync(
    {
      open: async (spec) => {
        calls += 1;
        if (calls === 1) throw new Error("no monitor");
        opened.push(spec.label);
      },
      close: () => {},
      send: () => {},
    },
    () => [typeBox],
  );
  await sync.sync();
  await new Promise((r) => setTimeout(r, 1500));  // the owner waits, then looks
  assert.deepEqual(opened, ["pane-type"], "the text box stays unopened until something else changes");
});

// Fixed by S1 (2026-11-05): such an error is never shown over a waiting card; bad_message isn't shown at all.
test("O-05: a protocol error with no run id does not wipe the confirm card the backend still waits on", () => {
  // The backend answers a frame it can't read with ``error`` {code: "bad_message"} and no run id
  // (ipc/server.py). The presenter treats it as the answer: the confirm card and its countdown go,
  // while the backend still holds the card open (and counts it down as seen).
  let p = onState(initial, "confirm", "r1", "t1").p;
  p = onConfirm(p, "swift:1", "r1", 45, 0);
  p = onAnswer(p, { kind: "error", ms: 12000 }, 10).p;
  assert.equal(p.pendingConfirm, "swift:1", "the card waiting for an answer is gone from the screen");
});

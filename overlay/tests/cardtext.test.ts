import assert from "node:assert/strict";
import { test } from "node:test";

import { cardLines, hasMarkedLines } from "../src/cardtext.ts";

test("marked lines are the agent's, and lose only the mark", () => {
  assert.deepEqual(cardLines("In:\n│ C:\\p\\a.py\nreplace:\n│     indented\n│ \nwith:\n(nothing)"), [
    { text: "In:", agent: false },
    { text: "C:\\p\\a.py", agent: true },
    { text: "replace:", agent: false },
    { text: "    indented", agent: true },
    { text: "", agent: true },
    { text: "with:", agent: false },
    { text: "(nothing)", agent: false },
  ]);
});

test("a mark the agent wrote itself stays visible inside its own line", () => {
  assert.deepEqual(cardLines("│ │ with:"), [{ text: "│ with:", agent: true }]);
});

test("only file changes have marked lines: a command is shown as it came", () => {
  for (const tool of ["Write", "Edit", "MultiEdit", "NotebookEdit"]) assert.equal(hasMarkedLines(tool), true);
  for (const tool of ["Bash", "PowerShell", "send_email", ""]) assert.equal(hasMarkedLines(tool), false);
});

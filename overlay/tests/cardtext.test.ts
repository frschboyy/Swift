import assert from "node:assert/strict";
import { test } from "node:test";

import { cardLines, hasMarkedLines, quoteLines, recipientText } from "../src/cardtext.ts";

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

test("a recipient from the owner's own words is marked; a contact isn't (foundation decision 5)", () => {
  assert.equal(recipientText({ name: "Ada Lovelace", email: "ada@example.edu" }), "Ada Lovelace <ada@example.edu>");
  assert.equal(recipientText({ name: "ada@example.com", email: "ada@example.com", said: true }),
    "ada@example.com (from your words, not in your contacts)");
});

test("a question's quote is every line of what it would write, each marked as the worker's (decision 6)", () => {
  const text = `${"a long line ".repeat(40)}\n\nsecond paragraph`;
  const lines = quoteLines(text);
  assert.equal(lines.map((l) => l.text).join("\n"), text);  // nothing clipped or left out
  assert.ok(lines.every((l) => l.agent));
  assert.deepEqual(quoteLines(""), []);
});

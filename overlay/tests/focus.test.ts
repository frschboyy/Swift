// "Swift never takes focus; the text box is the only exception" (CLAUDE.md), and A7's keyboard entry goes through
// it. These read the code: the only place a window takes the keyboard is the text box's creation, and the text box
// opens only from the owner's own hotkeys, the tray, or a click on Change, never because a card appeared.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");
const lines = (src: string, re: RegExp): string[] => src.split(/\r?\n/).filter((l) => re.test(l)).map((l) => l.trim());

test("only the text box's window takes the keyboard (Rust)", () => {
  const rust = read("../src-tauri/src/lib.rs") + read("../src-tauri/src/win.rs");
  const focus = lines(rust, /set_focus\(\)|SetForegroundWindow\(|SetFocus\(/).filter((l) => !l.startsWith("//"));
  assert.deepEqual(focus, ["let _ = window.set_focus();"]);
  assert.match(rust, /if typing \{\s*\/\/[^\n]*\n\s*let _ = window\.set_focus\(\);/);
});

test("A7: keyboard entry opens only from its hotkey; the text box only from a hotkey, the tray or Change", () => {
  const main = read("../src/main.ts");
  assert.deepEqual(lines(main, /enterCard\(\);/), ["enterCard();"]);
  assert.match(main, /payload\.name === "card" && payload\.state === "down"\) \{\s*enterCard\(\);/);
  const opens = lines(main, /toggleTyping\(\)/).filter((l) => !l.startsWith("function") && !l.startsWith("/**"));
  assert.equal(opens.length, 4, opens.join("\n"));  // the type hotkey, the tray, Change, and A7's enterCard
  assert.ok(opens.some((l) => l.includes('"Change"')) && opens.some((l) => l.startsWith("if (!typing) toggleTyping();")));
});

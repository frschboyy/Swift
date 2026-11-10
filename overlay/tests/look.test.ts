// The Halo look spike (ADR-019 Step A): behind a dev-only switch, on tokens.css's values, and off by
// default. How it looks is for the harness and the owner's checks.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { needsCompact, tailX } from "../src/look/geometry.ts";
import { lookFrom } from "../src/look/index.ts";

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");

test("the look is off unless asked for, and the URL wins over the environment", () => {
  assert.equal(lookFrom("", undefined), null);
  assert.equal(lookFrom("?theme=dark", ""), null);
  assert.equal(lookFrom("?look=paper", undefined), null);
  assert.equal(lookFrom("", "anything"), null);
  assert.equal(lookFrom("?look=halo", undefined), "halo");
  assert.equal(lookFrom("", "halo"), "halo");
  assert.equal(lookFrom("?look=default", "halo"), null);
});

test("only a dev build reaches the look: the bundler drops the import from a release build", () => {
  for (const file of ["../src/main.ts", "../src/pane.ts"]) {
    const lines = read(file).split(/\r?\n/).filter((l) => l.includes('"./look"'));
    assert.equal(lines.length, 1, file);
    assert.match(lines[0], /^if \(import\.meta\.env\.DEV\) void import\("\.\/look"\)/, file);
  }
  for (const file of ["../index.html", "../src/styles.css", "../src/entry.ts"]) {
    assert.doesNotMatch(read(file), /data-look|look\/|look=/, file);
  }
});

/** ``--name: value`` for each declaration of the first block whose selector matches. */
function block(css: string, selector: RegExp): Map<string, string> {
  const at = css.search(selector);
  assert.ok(at >= 0, String(selector));
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("\n}", at));
  return new Map([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

test("every value in the design's tokens.css is in the look, unchanged", () => {
  const design = read("../../docs/design/halo-system/tokens.css");
  const look = read("../src/look/halo.css");
  const pairs: [RegExp, RegExp][] = [
    [/#stage,\s*#stage\[data-theme="dark"\] \{/, /#stage\[data-look="halo"\],\s*#stage\[data-look="halo"\]\[data-theme="dark"\] \{/],
    [/#stage\[data-theme="light"\] \{/, /#stage\[data-look="halo"\]\[data-theme="light"\] \{/],
    [/\n#stage \{/, /\n#stage\[data-look="halo"\] \{/],
  ];
  for (const [from, to] of pairs) {
    const tokens = block(design, from);
    const drawn = block(look, to);
    assert.ok(tokens.size > 10);
    for (const [name, value] of tokens) assert.equal(drawn.get(name), value, name);
  }
});

test("every rule in the look is under the switch", () => {
  const css = read("../src/look/halo.css").replace(/\/\*[\s\S]*?\*\//g, "");
  // Without what's in brackets: a comma inside :has(…) doesn't start a selector.
  const flat = css.replace(/@media[^{]+\{/g, "").replace(/\{[^{}]*\}/g, "\n").replace(/\((?:[^()]|\([^()]*\))*\)/g, "");
  for (const selector of flat.split(/[,\n]/).map((s) => s.trim()).filter((s) => s && s !== "}")) {
    assert.match(selector, /^#stage\[data-look="halo"\]/, selector);
  }
});

test("the tail sits at the orb (SPEC §9): 32 left, 244 centre, 456 right, and never reaches a corner", () => {
  assert.equal(tailX(16 + 44, 16, 512), 32);
  assert.equal(tailX(360, 104, 512), 244);
  assert.equal(tailX(720 - 16 - 44, 192, 512), 456);
  assert.equal(tailX(0, 16, 512), 28);
  assert.equal(tailX(9999, 16, 512), 460);
});

test("compact confirm (SPEC §10) needs a confirm, edges behind it and a tight window", () => {
  assert.equal(needsCompact(true, 3, 412, 102, 560), true);
  assert.equal(needsCompact(true, 3, 341, 102, 560), false);
  assert.equal(needsCompact(true, 0, 500, 0, 560), false);
  assert.equal(needsCompact(false, 3, 412, 102, 560), false);
});

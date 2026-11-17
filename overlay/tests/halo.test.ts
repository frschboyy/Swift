// Halo, the only look (ADR-019 Step B): styles.css carries tokens.css's values, there is no switch, and
// the layout rules hold. How it looks is for the harness and the owner's checks.
import { strict as assert } from "node:assert";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { needsCompact, tailX } from "../src/geometry.ts";

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");

test("no look switch is left anywhere in the overlay", () => {
  const files = ["../index.html", "../dev/b4.html", ...readdirSync(new URL("../src/", import.meta.url)).filter((f) => /\.(ts|css)$/.test(f)).map((f) => `../src/${f}`)];
  // Built from parts, so this file doesn't match itself.
  const switchWords = new RegExp(["data-" + "look", "VITE_SWIFT_" + "LOOK", "look=" + "halo"].join("|"));
  for (const file of files) assert.doesNotMatch(read(file), switchWords, file);
});

/** ``--name: value`` for each declaration of the first block whose selector matches. */
function block(css: string, selector: RegExp): Map<string, string> {
  const at = css.search(selector);
  assert.ok(at >= 0, String(selector));
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("\n}", at));
  return new Map([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

test("every value in the design's tokens.css is in styles.css, unchanged", () => {
  const design = read("../../docs/design/halo-system/tokens.css");
  const styles = read("../src/styles.css");
  for (const selector of [/#stage,\s*#stage\[data-theme="dark"\] \{/, /#stage\[data-theme="light"\] \{/, /\n#stage \{/]) {
    const tokens = block(design, selector);
    const drawn = block(styles, selector);
    assert.ok(tokens.size > 10);
    for (const [name, value] of tokens) assert.equal(drawn.get(name), value, name);
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

test("with reduced motion the spinner still turns, slowly (A3: Windows' animation effects off)", () => {
  const css = read("../src/styles.css");
  const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
  const block = reduced.slice(0, reduced.indexOf("\n}\n"));
  assert.match(block, /animation: none !important/);
  assert.match(block, /\.spinner \{ animation: spin [\d.]+s linear infinite !important; \}/);
});

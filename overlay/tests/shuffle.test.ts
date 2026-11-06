// The one timing curve (ADR-018 §2.4). What it animates is checked in the dev harness.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { EASE, FADE_MS, isStill, MOVE_MS, over } from "../src/shuffle.ts";

const box = (left: number, top: number, width: number, height: number) => ({ left, top, width, height });

test("the transform puts an element laid out here over where it was", () => {
  assert.equal(over(box(100, 200, 500, 50), box(100, 300, 500, 50)), "translate(0px, 100px) scale(1.000, 1.000)");
  assert.equal(over(box(0, 0, 500, 100), box(10, 20, 250, 50)), "translate(10px, 20px) scale(0.500, 0.500)");
});

test("a shape doesn't crush to a line, or blow up from one", () => {
  assert.equal(over(box(0, 0, 500, 100), box(0, 0, 12, 12)), "translate(0px, 0px) scale(0.300, 0.300)");
  assert.equal(over(box(0, 0, 12, 12), box(0, 0, 500, 500)), `translate(0px, 0px) scale(${(1 / 0.3).toFixed(3)}, ${(1 / 0.3).toFixed(3)})`);
  assert.equal(over(box(0, 0, 0, 0), box(5, 5, 10, 10)), "translate(5px, 5px) scale(1.000, 1.000)");
});

test("moving less than a pixel isn't a move", () => {
  assert.equal(isStill(box(10, 10, 5, 5), box(10.4, 9.6, 5, 5)), true);
  assert.equal(isStill(box(10, 10, 5, 5), box(10, 12, 5, 5)), false);
});

test("one curve: the design's easing, the ADR's times, and the stylesheet's easing is the same", () => {
  assert.equal(MOVE_MS, 280);
  assert.equal(FADE_MS, 120);
  const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  const ease = /--ease: (cubic-bezier\([^)]*\));/.exec(css);
  assert.equal(ease?.[1], EASE);
  // Never overshooting: both control points' y stay within 0 to 1.
  const [, y1, , y2] = EASE.slice(13, -1).split(",").map(Number);
  assert.ok(y1 >= 0 && y1 <= 1 && y2 >= 0 && y2 <= 1);
});

// One timing curve for everything that moves (ADR-018 §2.4): the design's easing, never overshooting,
// 280 ms for moves. An element is laid out where it ends up and animated from where it was, so a click
// and a hit region always see its real place. With reduced motion it's a 120 ms fade, or nothing.

export const MOVE_MS = 280;
export const FADE_MS = 120;
export const EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";
// B7 (tokens-b8.css --dur-*/--ease-*): a card folds into the orb, an edge comes forward to the card, Done drains.
export const FOLD_MS = 220;
export const EASE_FOLD = "cubic-bezier(0.4, 0, 1, 1)";
export const EDGE_MS = 320;
export const DRAIN_MS = 400;
/** Done drains toward the orb by this much as it fades. */
export const DRIFT_PX = 8;
/** A shape never starts smaller than this share of its own size, so its words don't crush. */
const MIN_SCALE = 0.3;

export type Box = { left: number; top: number; width: number; height: number };

const fit = (from: number, to: number): number => (to > 0 ? Math.max(MIN_SCALE, Math.min(1 / MIN_SCALE, from / to)) : 1);

/** The transform that puts a box laid out at ``at`` over ``over``, measured from its top-left corner. */
export function over(at: Box, there: Box): string {
  const dx = Math.round(there.left - at.left);
  const dy = Math.round(there.top - at.top);
  return `translate(${dx}px, ${dy}px) scale(${fit(there.width, at.width).toFixed(3)}, ${fit(there.height, at.height).toFixed(3)})`;
}

export const isStill = (a: Box, b: Box): boolean => Math.abs(a.left - b.left) < 1 && Math.abs(a.top - b.top) < 1;

// Windows' "Animation effects" off, or the owner's "Motion: Less" (A8, display.ts).
const reduced = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "less";

/** A webview that isn't being painted holds an animation on its first frame, which would leave an
 * element invisible and its hit region wrong. A timer still runs there, so it always ends. */
function run(node: HTMLElement, frames: Keyframe[], ms: number, easing = EASE): Animation {
  const anim = node.animate(frames, { duration: ms, easing });
  window.setTimeout(() => {
    if (anim.playState === "running") anim.finish();
  }, ms + 20);
  return anim;
}

/** ``node`` has just been laid out where it belongs: it comes there from ``from``. ``fade``: appearing. */
export function moveFrom(node: HTMLElement, from: Box, fade = false, ms = MOVE_MS): void {
  if (reduced()) {
    if (fade) fadeIn(node);
    return;
  }
  const at = node.getBoundingClientRect();
  if (!fade && isStill(at, from)) return;
  run(node, [
    { transformOrigin: "0 0", transform: over(at, from), ...(fade ? { opacity: 0 } : {}) },
    { transformOrigin: "0 0", transform: "none", ...(fade ? { opacity: 1 } : {}) },
  ], ms);
}

/** ``node`` leaves for ``to``, fading, and is drawn no more: ``done`` runs when it has gone. B7: it folds into
 * the orb in FOLD_MS on the fold curve; ``drain`` (Done after its reading time) fades over DRAIN_MS instead,
 * drifting DRIFT_PX toward ``to``. Reduced motion: a FADE_MS fade only. */
export function leaveTo(node: HTMLElement, to: Box | null, done: () => void, drain = false): void {
  const at = node.getBoundingClientRect();
  const away = !to || reduced() ? "none" : drain ? drift(at, to) : over(at, to);
  const anim = run(node, [
    { transformOrigin: "0 0", transform: "none", opacity: 1 },
    { transformOrigin: "0 0", transform: away, opacity: 0 },
  ], reduced() ? FADE_MS : drain ? DRAIN_MS : FOLD_MS, reduced() ? "linear" : drain ? "ease-in" : EASE_FOLD);
  // The promise, not the finish event: that waits for a painted frame too.
  void anim.finished.then(done, done);
}

/** A small step from ``at`` toward ``to``'s centre (Done draining toward the orb). */
export function drift(at: Box, to: Box): string {
  const dx = to.left + to.width / 2 - (at.left + at.width / 2);
  const dy = to.top + to.height / 2 - (at.top + at.height / 2);
  const d = Math.hypot(dx, dy) || 1;
  return `translate(${Math.round((dx / d) * DRIFT_PX)}px, ${Math.round((dy / d) * DRIFT_PX)}px)`;
}

export function fadeIn(node: HTMLElement): void {
  run(node, [{ opacity: 0 }, { opacity: 1 }], FADE_MS);
}

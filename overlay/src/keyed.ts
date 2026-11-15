// The keyboard on the card's own buttons (foundation decision 2). The overlay window never takes focus, so the
// text box holds the keyboard: Tab there reaches the card's buttons (the card rings the one reached) and Enter
// presses it, the same click as the mouse's (``confirm.reply``/``ask.reply``, source click). Each button's key
// carries its card's id, so a button reached on one card is never pressed on the next.

/** The button Tab (``dir`` 1) or Shift+Tab (-1) reaches from ``at`` among the card's ``keys`` (in Tab order):
 * from the text, the first (or last); past either end, back to the text (null). */
export function step(keys: string[], at: string | null, dir: 1 | -1): string | null {
  const i = at === null ? -1 : keys.indexOf(at);
  if (i < 0) return keys.length ? (dir === 1 ? keys[0] : keys[keys.length - 1]) : null;
  return keys[i + dir] ?? null;
}

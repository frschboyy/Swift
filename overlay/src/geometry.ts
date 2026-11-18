// Halo's two layout rules, pure so Node can test them (ADR-019).

/** What the window keeps free of card and deck (SPEC §10: 560 − 466). */
const WINDOW_KEEPS = 94;

/** Tail x (SPEC §9): at the orb, clamped so it never reaches the card's corners. */
export function tailX(orbCentre: number, cardLeft: number, cardWidth: number): number {
  return Math.min(Math.max(orbCentre - cardLeft - 12, 28), cardWidth - 52);
}

/** ADR-019 §8.6, after the compact rule: a compact confirm that still doesn't fit with more than one edge
 * behind it folds the deck to one edge (34 px). The card never scrolls; its buttons never leave the window. */
export function needsFold(isConfirm: boolean, edges: number, cardHeight: number, deckHeight: number, windowHeight: number): boolean {
  return isConfirm && edges > 1 && cardHeight + deckHeight > windowHeight - WINDOW_KEEPS;
}

/** The compact confirm rule (SPEC §10): only with edges behind a confirm that wouldn't fit otherwise. */
export function needsCompact(isConfirm: boolean, edges: number, cardHeight: number, deckHeight: number, windowHeight: number): boolean {
  return isConfirm && edges > 0 && cardHeight + deckHeight > windowHeight - WINDOW_KEEPS;
}

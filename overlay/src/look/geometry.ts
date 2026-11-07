// Halo's two layout rules, pure so Node can test them (ADR-019 Step A).

/** What the window keeps free of card and deck (SPEC §10: 560 − 466). */
const WINDOW_KEEPS = 94;

/** Tail x (SPEC §9): at the orb, clamped so it never reaches the card's corners. */
export function tailX(orbCentre: number, cardLeft: number, cardWidth: number): number {
  return Math.min(Math.max(orbCentre - cardLeft - 12, 28), cardWidth - 52);
}

/** The compact confirm rule (SPEC §10): only with edges behind a confirm that wouldn't fit otherwise. */
export function needsCompact(isConfirm: boolean, edges: number, cardHeight: number, deckHeight: number, windowHeight: number): boolean {
  return isConfirm && edges > 0 && cardHeight + deckHeight > windowHeight - WINDOW_KEEPS;
}

// ADR-019 §8.2: times on a card are relative. Running m:ss (views.ts elapsed); Done and Failed "just now",
// "N min ago", "N h ago"; Due "now". Clock times only in the reader and the record.

/** How long ago something ended, in the card's words. */
export function ago(atMs: number, nowMs: number): string {
  const min = Math.floor(Math.max(0, nowMs - atMs) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  return `${Math.floor(min / 60)} h ago`;
}

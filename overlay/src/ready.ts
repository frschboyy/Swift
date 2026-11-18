// D10 (Halo B8, owner's default): "Swift is ready" only after an update or a crash, not on every start.
// What the last launch left: its version, and whether it ended cleanly. Kept in the overlay's own
// storage; a storage that fails (cleared, blocked) says ready, as before.

export type LastRun = { version: string; clean: boolean };

/** Whether this start says "Swift is ready". */
export const saysReady = (last: LastRun | null, version: string): boolean =>
  last === null || last.version !== version || !last.clean;

const KEY = "swift.lastRun";

/** Reads what the last launch left, and marks this one as running (not yet ended cleanly). */
export function startRun(version: string, store: Pick<Storage, "getItem" | "setItem"> = localStorage): LastRun | null {
  let last: LastRun | null = null;
  try {
    const raw = store.getItem(KEY);
    last = raw ? (JSON.parse(raw) as LastRun) : null;
    store.setItem(KEY, JSON.stringify({ version, clean: false }));
  } catch {
    return null;
  }
  return last;
}

/** This launch is ending as asked (Quit, Restart): the next start isn't after a crash. */
export function endRun(version: string, store: Pick<Storage, "setItem"> = localStorage): void {
  try {
    store.setItem(KEY, JSON.stringify({ version, clean: true }));
  } catch {
    // nothing to keep: the next start says ready
  }
}

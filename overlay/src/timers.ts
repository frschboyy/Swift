// Halo B14: a running timer has no card; the orb wears its ring and a time pill. Pure: main.ts draws it.
import type { TimerRow } from "./protocol";

/** Time left as the pill says it: "4:12", under a minute "0:42", two or more timers "4:12 · 2" (D6). */
export function pillText(items: TimerRow[], now: number): string {
  if (!items.length) return "";
  const s = Math.max(0, Math.ceil((items[0].due_ms - now) / 1000));
  const time = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return items.length > 1 ? `${time} · ${items.length}` : time;
}

/** Edge · Got it after Done on a timer's Due card: "Your tea timer is up." → "Done: Tea timer". */
export function doneLine(summary: string): string {
  const name = /^Your (.+?) is up\./.exec(summary)?.[1] ?? "timer";
  return `Done: ${name.charAt(0).toUpperCase()}${name.slice(1)}`;
}

/** How much of the soonest timer is left, 1 to 0: the ring's arc. */
export function left(items: TimerRow[], now: number): number {
  if (!items.length) return 0;
  const t = items[0];
  const total = t.due_ms - t.set_ms;
  return total > 0 ? Math.min(1, Math.max(0, (t.due_ms - now) / total)) : 0;
}

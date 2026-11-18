// A12 (Explore, off by default): the orb glance. Read-only lines about what's running and waiting. Pure.
import type { StackEntry, TimerRow } from "./protocol";

export type GlanceLine = { text: string; warn?: boolean };

/** Running timers, then what's waiting, amber only when an OK waits; one quiet line when there's nothing. */
export function glanceLines(timers: TimerRow[], waiting: StackEntry[], now: number): GlanceLine[] {
  const lines: GlanceLine[] = [];
  const counting = timers.filter((t) => t.due_ms > now);
  if (counting.length) {
    const s = Math.ceil((counting[0].due_ms - now) / 1000);
    const left = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    lines.push({ text: `${counting.length === 1 ? counting[0].title : `${counting.length} timers`} · ${left} left` });
  }
  if (waiting.length) {
    const oks = waiting.filter((i) => i.kind !== "parked" && i.kind !== "due").length;
    lines.push({ text: `${waiting.length} waiting${oks ? ` · ${oks} ${oks === 1 ? "needs" : "need"} your OK` : ""}`, warn: oks > 0 });
  }
  return lines.length ? lines : [{ text: "Nothing waiting, nothing running" }];
}

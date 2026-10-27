// Which extra windows the overlay has open, and what each shows (ADR-015 §3). Pure: no DOM, no Tauri.
//
// The main window keeps the card in front. Each other running request gets a small window of
// its own (a "request" pane, instead of ADR-013's rows), and a long answer can open in a reader
// pane. main.ts opens, updates and closes real windows to match ``wantedPanes``; the panes
// themselves only draw what they are told and send clicks back.

import type { ResultDetails } from "./protocol";
import type { Presenter, Row } from "./presenter";

export type PaneKind = "request" | "reader";

/** What a pane window draws. */
export type PaneView =
  | { kind: "request"; runId: string; title: string; label: string; startedMs: number; running: boolean; state: string }
  | { kind: "reader"; title: string; summary: string; details: ResultDetails | null; chip: boolean };

export type PaneSpec = { label: string; kind: PaneKind; index: number; view: PaneView };

/** A long answer open in the reader (null: closed). */
export type Reader = {
  title: string;
  summary: string;
  details: ResultDetails | null;
  runId: string | null;
  // The last time the owner looked at it (opened, hovered, scrolled): it shrinks to a chip after a quiet period.
  touchedAt: number;
  chip: boolean;
} | null;

/** Request windows at most: the run limit (ADR-013 §5.2), the same as presenter.MAX_ROWS. */
export const MAX_PANES = 3;
/** No pointer or scrolling on the reader this long: it shrinks to a chip (ADR-015 §3.3). */
export const READER_QUIET_MS = 60_000;
/** No news and no pointer on a working card this long: it collapses to its one line. */
export const WORKING_QUIET_MS = 30_000;
/** An answer longer than this, or with more rows than this, gets "Read all". */
export const READ_ALL_CHARS = 600;
export const READ_ALL_ROWS = 6;

const ENDED: ReadonlySet<string> = new Set(["result", "error", "done"]);

/** Window labels: Tauri allows letters, digits and - / : _. */
export const paneLabel = (kind: PaneKind, id = ""): string =>
  kind === "reader" ? "pane-reader" : `pane-run-${id.replace(/[^A-Za-z0-9_-]/g, "_")}`;

/** The panes that should exist now. ``label`` says what a row is doing, in words. */
export function wantedPanes(p: Presenter, reader: Reader, label: (r: Row) => string): PaneSpec[] {
  const out: PaneSpec[] = [];
  // Requests waiting for a slot are a line on the card in front, not a window.
  requestRows(p).forEach((r, index) => {
    out.push({
      label: paneLabel("request", r.runId),
      kind: "request",
      index,
      view: { kind: "request", runId: r.runId, title: r.title, label: label(r), startedMs: r.startedMs, running: !ENDED.has(r.state), state: r.state },
    });
  });
  if (reader) {
    out.push({
      label: paneLabel("reader"),
      kind: "reader",
      index: 0,
      view: { kind: "reader", title: reader.title, summary: reader.summary, details: reader.details, chip: reader.chip },
    });
  }
  return out;
}

/** The other requests that get a window: running or just ended, at most MAX_PANES. */
export const requestRows = (p: Presenter): Row[] => p.rows.filter((r) => r.state !== "queued").slice(0, MAX_PANES);

/** Requests waiting for a slot: a line on the card in front. */
export const queuedRows = (p: Presenter): Row[] => p.rows.filter((r) => r.state === "queued");

/** Open the reader on an answer. */
export function openReader(title: string, summary: string, details: ResultDetails | null, runId: string | null, now: number): Reader {
  return { title, summary, details, runId, touchedAt: now, chip: false };
}

/** The owner looked at the reader (hover, scroll, a click on its chip): full size again, quiet clock reset. */
export const touchReader = (r: Reader, now: number): Reader => (r ? { ...r, touchedAt: now, chip: false } : r);

/** The clock: a reader nobody has looked at for READER_QUIET_MS shrinks to a chip. */
export function readerTick(r: Reader, now: number, hovering: boolean): Reader {
  if (!r) return r;
  if (hovering) return r.chip ? r : { ...r, touchedAt: now };
  if (!r.chip && now - r.touchedAt >= READER_QUIET_MS) return { ...r, chip: true };
  return r;
}

/** A working card with no news and no pointer for WORKING_QUIET_MS collapses to its one line. */
export const workingQuiet = (lastNewsAt: number, now: number, hovering: boolean): boolean =>
  !hovering && lastNewsAt > 0 && now - lastNewsAt >= WORKING_QUIET_MS;

/** An answer too long for the card: it scrolls there, and "Read all" opens the reader. */
export function needsReader(summary: string, details: ResultDetails | null | undefined): boolean {
  if (summary.length > READ_ALL_CHARS) return true;
  if (!details) return false;
  switch (details.kind) {
    case "text":
      return summary.length + details.text.length > READ_ALL_CHARS;
    case "list":
      return details.items.length > READ_ALL_ROWS;
    case "table":
      return details.rows.length > READ_ALL_ROWS;
  }
}

/** What changed between what the windows show and what they should: open, update, close. */
export function diffPanes(
  open: ReadonlyMap<string, string>,
  wanted: PaneSpec[],
): { create: PaneSpec[]; update: PaneSpec[]; close: string[] } {
  const create: PaneSpec[] = [];
  const update: PaneSpec[] = [];
  for (const spec of wanted) {
    const shown = open.get(spec.label);
    if (shown === undefined) create.push(spec);
    else if (shown !== JSON.stringify(spec.view)) update.push(spec);
  }
  const keep = new Set(wanted.map((s) => s.label));
  return { create, update, close: [...open.keys()].filter((l) => !keep.has(l)) };
}

/** A pane's size before it measures itself (CSS px). */
export function paneSize(spec: PaneSpec): { w: number; h: number } {
  if (spec.view.kind === "request") return { w: 300, h: 44 };
  return spec.view.chip ? { w: 300, h: 44 } : { w: 560, h: 420 };
}

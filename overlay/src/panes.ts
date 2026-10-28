// Which extra windows the overlay has open, and what each shows (ADR-015 §3). Pure: no DOM, no Tauri.
//
// The main window keeps the card in front. Each other running request gets a small window of
// its own (a "request" pane, instead of ADR-013's rows), and a long answer can open in a reader
// pane. main.ts opens, updates and closes real windows to match ``wantedPanes``; the panes
// themselves only draw what they are told and send clicks back.
//
// ADR-015 §9, §10 (2026-10-27): the waiting stack is a pane of its own in a bottom corner, and
// typing to Swift opens a text box pane, the one window that takes the keyboard.
//
// The Capsule redesign (ADR-017): chips are 280 × 56, the stack 280 × 80 closed and 320 wide
// open, the text box 512 × 52 (a notice row above it while a confirm card is open: typing can't
// approve), and the tray menu is a pane of its own, opened by a click on the tray icon.
//
// ADR-017 §11: a running request's live view (live.ts) is a pane of its own, one per request.

import type { LiveView } from "./live";
import type { ResultDetails } from "./protocol";
import type { Presenter, Row } from "./presenter";
import type { StackView } from "./stack";

export type PaneKind = "request" | "reader" | "stack" | "type" | "tray" | "live";

/** The text box (ADR-015 §10): what was typed so far, and the conversation it follows up, if any.
 * ``confirm``: a confirm card is open, so the box says typing can't approve it (Enter = Change). */
export type TypeView = { kind: "type"; draft: string; follows: string | null; confirm?: boolean };

/** The tray menu (ADR-017): Swift's status, where the overlay sits, and the menu's actions. */
export type TrayView = {
  kind: "tray";
  status: string;
  // Listening paused by the owner: the item says Resume listening.
  paused: boolean;
  anchor: string;
  smart: boolean;
  // The typing hotkey as written in config.yaml ("ctrl+space"), or null when there is none.
  typeKey: string | null;
};

/** What a pane window draws. */
export type PaneView =
  | { kind: "request"; runId: string; title: string; words: string; label: string; startedMs: number; running: boolean; state: string }
  | { kind: "reader"; title: string; summary: string; details: ResultDetails | null; chip: boolean }
  | StackView
  | TypeView
  | TrayView
  | LiveView;

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

/** Request windows at most: the other requests running (the run limit, ADR-013 §5.2) and a couple
 * waiting for a slot; each gets a chip at once so the owner sees it registered (bug 4, 2026-10-27). */
export const MAX_PANES = 5;
/** A request this young gets no window yet: most answers beside a run take a few ms (the time),
 * and a window that opens and closes at once is noise. The main card says "Got it" meanwhile. */
export const CHIP_DELAY_MS = 600;
/** "Got it: …" on the main card for a request that started beside the one in front. */
export const ACK_MS = 2500;
/** No pointer or scrolling on the reader this long: it shrinks to a chip (ADR-015 §3.3). */
export const READER_QUIET_MS = 60_000;
/** No news and no pointer on a working card this long: it collapses to its one line. */
export const WORKING_QUIET_MS = 12_000;
/** An answer longer than this, or with more rows than this, gets "Read all". */
export const READ_ALL_CHARS = 600;
export const READ_ALL_ROWS = 6;

const ENDED: ReadonlySet<string> = new Set(["result", "error", "done"]);

/** Window labels: Tauri allows letters, digits and - / : _. */
export const paneLabel = (kind: PaneKind, id = ""): string =>
  kind === "request" || kind === "live"
    ? `pane-${kind === "request" ? "run" : "live"}-${id.replace(/[^A-Za-z0-9_-]/g, "_")}`
    : `pane-${kind}`;

/** Besides the requests and the reader: the waiting stack and the text box, when they show. */
export type Extra = { stack?: StackView | null; typing?: TypeView | null; tray?: TrayView | null; live?: LiveView[]; now?: number };

/** The panes that should exist now. ``label`` says what a row is doing, in words. */
export function wantedPanes(p: Presenter, reader: Reader, label: (r: Row) => string, extra: Extra = {}): PaneSpec[] {
  const out: PaneSpec[] = [];
  const now = extra.now;
  requestRows(p)
    .filter((r) => now === undefined || now - r.startedMs >= CHIP_DELAY_MS)
    .forEach((r, index) => {
      out.push({
        label: paneLabel("request", r.runId),
        kind: "request",
        index,
        view: {
          kind: "request", runId: r.runId, title: r.title, words: r.words ?? r.title, label: label(r), startedMs: r.startedMs,
          running: !ENDED.has(r.state), state: r.state,
        },
      });
    });
  if (extra.stack) out.push({ label: paneLabel("stack"), kind: "stack", index: 0, view: extra.stack });
  if (extra.typing) out.push({ label: paneLabel("type"), kind: "type", index: 0, view: extra.typing });
  (extra.live ?? []).forEach((v, index) => out.push({ label: paneLabel("live", v.runId), kind: "live", index, view: v }));
  if (extra.tray) out.push({ label: paneLabel("tray"), kind: "tray", index: 0, view: extra.tray });
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

/** The other requests that get a window: running, waiting for a slot, or just ended; at most MAX_PANES. */
export const requestRows = (p: Presenter): Row[] => p.rows.slice(0, MAX_PANES);

/** Requests that weren't there before (not ended): the main card says "Got it" for each. */
export function newRows(known: ReadonlySet<string>, rows: Row[]): Row[] {
  return rows.filter((r) => !known.has(r.runId) && !ENDED.has(r.state));
}

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
  const v = spec.view;
  switch (v.kind) {
    case "request":
      return { w: 280, h: 56 };
    case "reader":
      return v.chip ? { w: 280, h: 56 } : { w: 560, h: 420 };
    case "stack":
      return v.expanded ? { w: 320, h: 64 + 76 * Math.min(6, v.items.length) } : { w: 280, h: 80 };
    case "type":
      return { w: 512, h: 52 + (v.confirm ? 44 : 0) + (v.follows ? 44 : 0) };
    case "tray":
      return { w: 280, h: 400 };
    case "live":
      return { w: 420, h: 480 };
  }
}

/** What PaneSync needs from the shell: open a window (rejects: no pane windows here), close one,
 * tell one what to show. */
export type PaneHost = {
  open(spec: PaneSpec): Promise<void>;
  close(label: string): void;
  send(label: string, view: PaneView): void;
};

/** Keeps the pane windows matching ``wanted()``, one change at a time.
 *
 * Opening a window takes a while. A second sync during it used to "close" a window that didn't
 * exist yet; the window opened then and nothing closed it, so a chip outlived its request and
 * counted up for minutes (bug 1, 2026-10-27: "What time is it? Working on it 2:44"). Here a sync
 * asked for while one runs runs again right after it, and sees the window it just opened. */
export class PaneSync {
  /** What each open window shows. */
  readonly shown = new Map<string, PaneView>();
  private running: Promise<void> | null = null;
  private again = false;
  /** False once opening a window failed: the caller draws rows instead. */
  available = true;

  private readonly host: PaneHost;
  private readonly wanted: () => PaneSpec[];
  private readonly onUnavailable: (err: unknown) => void;

  constructor(host: PaneHost, wanted: () => PaneSpec[], onUnavailable: (err: unknown) => void = () => {}) {
    this.host = host;
    this.wanted = wanted;
    this.onUnavailable = onUnavailable;
  }

  get busy(): boolean {
    return this.running !== null;
  }

  sync(): Promise<void> {
    if (!this.available) return Promise.resolve();
    if (this.running) {
      this.again = true;
      return this.running;
    }
    this.running = (async () => {
      do {
        this.again = false;
        await this.once();
      } while (this.again && this.available);
    })().finally(() => (this.running = null));
    return this.running;
  }

  /** Windows that are open but not wanted (from ``pane_labels``): close them. Not while syncing. */
  strays(open: string[]): string[] {
    return this.running ? [] : open.filter((label) => !this.shown.has(label));
  }

  private async once(): Promise<void> {
    const before = new Map([...this.shown].map(([label, view]) => [label, JSON.stringify(view)]));
    const d = diffPanes(before, this.wanted());
    for (const label of d.close) {
      this.shown.delete(label);
      this.host.close(label);
    }
    for (const spec of d.update) {
      this.shown.set(spec.label, spec.view);
      this.host.send(spec.label, spec.view);
    }
    for (const spec of d.create) {
      this.shown.set(spec.label, spec.view);
      try {
        await this.host.open(spec);
      } catch (err) {
        this.available = false;
        this.shown.clear();
        this.onUnavailable(err);
        return;
      }
      this.again = true;  // the world may have moved on while it opened: look again
      const view = this.shown.get(spec.label);
      if (view) this.host.send(spec.label, view);  // if it isn't listening yet, it asks ("ready")
    }
  }
}

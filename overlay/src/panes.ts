// Which extra windows the overlay has open, and what each shows (ADR-015 §3). Pure: no DOM, no Tauri.
//
// The main window keeps the card in front and the other requests behind it (ADR-018, deck.ts), and
// a long answer can open in a reader pane. main.ts opens, updates and closes real windows to match
// ``wantedPanes``; the panes themselves only draw what they are told and send clicks back.
//
// ADR-015 §9, §10 (2026-10-27): the waiting stack is a pane of its own in a bottom corner, and
// typing to Swift opens a text box pane, the one window that takes the keyboard.
//
// The Capsule redesign (ADR-017): the stack is 280 × 80 closed and 320 wide open, the text box 512 × 52 (a notice row above it while a confirm card is open: typing can't
// approve), and the tray menu is a pane of its own, opened by a click on the tray icon.
//
// ADR-017 §7: a running request's live view (live.ts) is a pane of its own, one per request.

import type { Display } from "./display";
import type { LiveView } from "./live";
import type { ResultDetails } from "./protocol";
import type { HistoryView, StackView } from "./stack";

export type PaneKind = "reader" | "stack" | "type" | "tray" | "live" | "history" | "workspace";

/** The text box (ADR-015 §10): what was typed so far, and the conversation it follows up, if any.
 * ``confirm``: a confirm card is open, so the box says typing can't approve it (Enter = Change). */
export type TypeView = {
  kind: "type"; draft: string; follows: string | null; confirm?: boolean;
  // Decision 2: the card has buttons Tab reaches (``reach``), and the one reached, by its label (``onCard``).
  reach?: boolean; onCard?: string | null;
  // Fix mode (heardfix.ts): correcting what Swift heard on a request's clip. Enter saves a label only.
  fix?: { clip: string; heard: string };
};

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
  // A8: how Swift shows things (display.ts).
  display?: Display;
  // Modes §3: "ask me about everything" is on: the status says so and "Stop asking about everything" shows.
  asking?: boolean;
};

/** Expand's workspace (owner, 2026-11-24, item 5): the card in front, at the screen edge on the orb's side, the work
 * area's height; ``w``: its width in CSS px (the content's rule, or the owner's own from resizing it). */
export type WorkspaceView = {
  kind: "workspace"; title: string; summary: string; details: ResultDetails | null; runId: string; pinned: boolean; w: number;
};

/** Expand's width: the owner's own if they resized it, else text a third of the screen (at least 560 px), a wide
 * block (a table, a chart, a diagram…) up to half. The shell keeps it to half the work area at most. */
export function workspaceWidth(details: ResultDetails | null | undefined, screenW: number, owners: number | null): number {
  if (owners && owners >= 400) return Math.round(owners);
  const wide = !!details && details.kind !== "text" && details.kind !== "list";
  return Math.round(wide ? screenW / 2 : Math.max(560, screenW / 3));
}

/** What a pane window draws. */
export type PaneView =
  | { kind: "reader"; title: string; summary: string; details: ResultDetails | null; chip: boolean }
  | StackView
  | TypeView
  | TrayView
  | LiveView
  | HistoryView
  | WorkspaceView;

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

/** No pointer or scrolling on the reader this long: it shrinks to a chip (ADR-015 §3.3). */
export const READER_QUIET_MS = 60_000;
/** No news and no pointer on a working card this long: it collapses to its one line. */
export const WORKING_QUIET_MS = 12_000;
/** An answer longer than this, or with more rows than this, gets "Read all". */
export const READ_ALL_CHARS = 600;
export const READ_ALL_ROWS = 6;

/** Window labels: Tauri allows letters, digits and - / : _. */
export const paneLabel = (kind: PaneKind, id = ""): string =>
  kind === "live" ? `pane-live-${id.replace(/[^A-Za-z0-9_-]/g, "_")}` : `pane-${kind}`;

/** Besides the reader: the waiting stack and the text box, when they show. */
export type Extra = { stack?: StackView | null; typing?: TypeView | null; tray?: TrayView | null; live?: LiveView[]; history?: HistoryView | null; workspace?: WorkspaceView | null };

/** The panes that should exist now. */
export function wantedPanes(reader: Reader, extra: Extra = {}): PaneSpec[] {
  const out: PaneSpec[] = [];
  if (extra.stack) out.push({ label: paneLabel("stack"), kind: "stack", index: 0, view: extra.stack });
  if (extra.typing) out.push({ label: paneLabel("type"), kind: "type", index: 0, view: extra.typing });
  (extra.live ?? []).forEach((v, index) => out.push({ label: paneLabel("live", v.runId), kind: "live", index, view: v }));
  if (extra.tray) out.push({ label: paneLabel("tray"), kind: "tray", index: 0, view: extra.tray });
  if (extra.history) out.push({ label: paneLabel("history"), kind: "history", index: 0, view: extra.history });
  if (extra.workspace) out.push({ label: paneLabel("workspace"), kind: "workspace", index: 0, view: extra.workspace });
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

export const STALL_MS = 20_000;

/** "Still working" after STALL_MS without news, on the steps only: never on the one-line card, which has
 * nowhere to show it (A3, 2026-11-13: it was redrawn every second for that, restarting its spinner). */
export const workingStalled = (oneLine: boolean, open: boolean, steps: number, lastStepAt: number, now: number): boolean =>
  !oneLine && !open && steps > 0 && now - lastStepAt > STALL_MS;

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
    case "compare":
    case "diagram":
    case "mindmap":
    case "preview":
    case "chart":
    case "cards":
    case "tree":
      return details.size === "expanded";  // Swift sized it (swift/shapes.py)
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
    case "reader":
      return v.chip ? { w: 280, h: 56 } : { w: 560, h: 420 };
    case "stack":
      // Pins add a 38 px pill each on the shelf above (at most 4, then a "+N pinned" line); it measures itself after.
      return { w: v.expanded ? 320 : 280, h: (v.expanded ? 64 + 76 * Math.min(6, v.items.filter((i) => i.kind !== "pinned").length) : 80)
        + 38 * Math.min(5, v.items.filter((i) => i.kind === "pinned").length) };
    case "type":
      return v.fix ? { w: 512, h: 200 } : { w: 512, h: 52 + (v.confirm ? 44 : 0) + (v.follows ? 44 : 0) };
    case "tray":
      return { w: 280, h: 400 };
    case "live":
      return { w: 420, h: 480 };
    case "history":
      return { w: 360, h: 600 };  // the shell gives it the work area's height on the right edge
    case "workspace":
      return { w: v.w, h: 600 };  // the work area's height on the orb's edge
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
 * exist yet; the window opened then and nothing closed it, so a request's own window outlived it and
 * counted up for minutes (bug 1, 2026-10-27: "What time is it? Working on it 2:44"). Here a sync
 * asked for while one runs runs again right after it, and sees the window it just opened. */
/** Whether ``err`` says this shell has no pane windows at all (the dev harness, an older shell). */
export function noPaneWindows(err: unknown): boolean {
  return /unhandled command|not found|unknown command|not allowed|isn't available/i.test(String(err));
}

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
        if (!noPaneWindows(err)) {
          // One window that couldn't open now (no monitor under the cursor while locked, …): tried
          // again on the next change. Turning pane windows off for good left the text box a
          // browser prompt that never shows in the app (owner checks 2026-11-04, 16b).
          this.shown.delete(spec.label);
          console.warn("[overlay] a pane window didn't open:", err);
          return;
        }
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

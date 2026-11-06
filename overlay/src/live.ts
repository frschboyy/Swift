// The live view of a running request (ADR-017 §7). Pure: no DOM, no Tauri, no timers.
//
// The backend sends ``live`` items for every request, in front or not: what it is doing now
// ("doing", from its steps), a page a search found or one being read ("source"), Claude's short
// notes between tool calls ("note"), and each paragraph Swift writes into the owner's app
// ("text"). This keeps them per request, so a view opened late shows what came before. Page
// titles and written text stay in the overlay: nothing here is logged or sent back.
//
// A view opens on "show me" (the backend's ``watch``) or the Watch action on a card or edge; one
// pane window per request, at most MAX_OPEN. It closes with ×, or LINGER_MS after its request
// ended unless the owner is looking at it; it then links the answer.

import type { ResultDetails } from "./protocol";
import type { Row } from "./presenter";

export type SourceState = "found" | "reading" | "read" | "failed";
export type Source = { url: string; title: string; site: string; state: SourceState };
export type Ended = { status: string; summary: string; details: ResultDetails | null; at: number };

export type LiveRun = {
  runId: string;
  title: string;
  words: string;
  startedMs: number;
  doing: { text: string; activity: string | null; app: string | null } | null;
  sources: Source[];
  notes: string[];
  // What Swift wrote into the owner's app, paragraph by paragraph, and the app.
  written: { app: string; text: string } | null;
  // A line from Swift about the view's own buttons ("Here it is in Word.").
  hint: string | null;
  ended: Ended | null;
  open: boolean;
  // The last time it opened or the owner pointed at it: it doesn't close by itself meanwhile.
  touchedAt: number;
};

export type Live = { runs: LiveRun[] };

/** What a live pane draws. */
export type LiveView = {
  kind: "live";
  runId: string;
  title: string;
  doing: string;
  activity: string | null;
  sources: Source[];
  notes: string[];
  written: { app: string; text: string } | null;
  hint: string | null;
  running: boolean;
  ended: { status: string; summary: string; answer: boolean } | null;
  startedMs: number;
};

export type LiveItem =
  | { kind: "doing"; text: string; activity?: string | null; app?: string | null }
  | { kind: "source"; url: string; title?: string; site?: string; state?: SourceState }
  | { kind: "note"; text: string }
  | { kind: "text"; text: string; app?: string | null }
  | { kind: "hint"; text: string };

/** Live views open at once (as many as requests can run side by side, ADR-013 §5.2). */
export const MAX_OPEN = 3;
export const MAX_SOURCES = 30;
export const MAX_NOTES = 12;
/** Written text kept per request; the view shows the end of it. */
export const MAX_WRITTEN = 20_000;
/** After its request ends, an open view stays this long since the owner last looked at it. */
export const LINGER_MS = 45_000;
/** A request this long over and with no view open is forgotten. */
export const FORGET_MS = 10 * 60_000;
/** Requests kept at most (the oldest ended one goes first). */
export const MAX_RUNS = 12;

export const initialLive: Live = { runs: [] };

const RANK: Record<SourceState, number> = { found: 0, reading: 1, read: 2, failed: 2 };

function fresh(runId: string, now: number): LiveRun {
  return {
    runId, title: "", words: "", startedMs: now, doing: null, sources: [], notes: [], written: null, hint: null,
    ended: null, open: false, touchedAt: now,
  };
}

function update(l: Live, runId: string, now: number, change: (r: LiveRun) => LiveRun): Live {
  const known = l.runs.find((r) => r.runId === runId);
  const next = change(known ?? fresh(runId, now));
  const runs = known ? l.runs.map((r) => (r === known ? next : r)) : [...l.runs, next];
  while (runs.length > MAX_RUNS) {
    const i = runs.findIndex((r) => r.ended && !r.open);
    if (i < 0) break;
    runs.splice(i, 1);
  }
  return { runs };
}

/** Only http(s) addresses are kept: the view opens them in the browser. */
export function webUrl(url: string): string | null {
  const u = url.trim();
  return /^https?:\/\/[^\s"'<>]+$/i.test(u) && u.length <= 2048 ? u : null;
}

function addSource(sources: Source[], s: Source): Source[] {
  const i = sources.findIndex((o) => o.url === s.url);
  if (i < 0) return [...sources, s].slice(-MAX_SOURCES);
  const old = sources[i];
  const merged: Source = {
    url: s.url,
    title: s.title || old.title,
    site: s.site || old.site,
    state: RANK[s.state] >= RANK[old.state] ? s.state : old.state,
  };
  return sources.map((o, j) => (j === i ? merged : o));
}

/** One ``live`` item from the backend. */
export function onItem(l: Live, runId: string, item: LiveItem, now: number): Live {
  return update(l, runId, now, (r) => {
    switch (item.kind) {
      case "doing":
        return item.text ? { ...r, doing: { text: item.text, activity: item.activity ?? null, app: item.app ?? null } } : r;
      case "source": {
        const url = webUrl(item.url ?? "");
        if (!url) return r;
        return { ...r, sources: addSource(r.sources, { url, title: item.title ?? "", site: item.site || siteOf(url), state: item.state ?? "found" }) };
      }
      case "note":
        return item.text && r.notes[r.notes.length - 1] !== item.text ? { ...r, notes: [...r.notes, item.text].slice(-MAX_NOTES) } : r;
      case "text": {
        const app = item.app || r.written?.app || "the app";
        const before = r.written?.text ?? "";
        const text = (before ? `${before}\n${item.text}` : item.text).slice(-MAX_WRITTEN);
        return { ...r, written: { app, text } };
      }
      case "hint":
        return { ...r, hint: item.text };
    }
  });
}

/** Open the view: "show me" (the backend's ``watch``) or a click on Watch. */
export function watch(l: Live, runId: string, title: string, words: string, now: number): Live {
  const opened = update(l, runId, now, (r) => ({ ...r, title: title || r.title, words: words || r.words, open: true, touchedAt: now }));
  const open = opened.runs.filter((r) => r.open);
  if (open.length <= MAX_OPEN) return opened;
  // Too many: the one looked at longest ago closes.
  const oldest = open.filter((r) => r.runId !== runId).sort((a, b) => a.touchedAt - b.touchedAt)[0];
  return close(opened, oldest.runId);
}

export const close = (l: Live, runId: string): Live => ({ runs: l.runs.map((r) => (r.runId === runId ? { ...r, open: false } : r)) });

export const touch = (l: Live, runId: string, now: number): Live =>
  ({ runs: l.runs.map((r) => (r.runId === runId && r.open ? { ...r, touchedAt: now } : r)) });

/** Its title, when the overlay learns it (the transcript, a row). */
export function name(l: Live, runId: string, title: string, words = ""): Live {
  if (!title || !l.runs.some((r) => r.runId === runId && !r.title)) return l;
  return { runs: l.runs.map((r) => (r.runId === runId && !r.title ? { ...r, title, words: words || r.words } : r)) };
}

/** The request ended: its answer (the request in front sends it whole), or a row's one line. */
export function ended(l: Live, runId: string, status: string, summary: string, details: ResultDetails | null, now: number): Live {
  if (!l.runs.some((r) => r.runId === runId)) return l;
  return { runs: l.runs.map((r) => (r.runId === runId && (!r.ended || (details && !r.ended.details))
    ? { ...r, ended: { status, summary: summary || r.ended?.summary || "", details: details ?? r.ended?.details ?? null, at: r.ended?.at ?? now }, doing: null }
    : r)) };
}

const ENDED_ROW: Record<string, string> = { result: "done", error: "error", done: "cancelled" };

/** Background requests: titles from their rows, and the end of one from its row's state. */
export function onRows(l: Live, rows: Row[], now: number): Live {
  let next = l;
  for (const row of rows) {
    next = name(next, row.runId, row.title, row.words ?? "");
    const status = ENDED_ROW[row.state];
    if (status) next = ended(next, row.runId, status, row.summary, null, now);
  }
  return next;
}

/** The clock: a view whose request ended closes once nobody has looked at it for LINGER_MS; old
 * ended requests are forgotten. ``hovered``: the runs whose view the pointer is on. */
export function tick(l: Live, now: number, hovered: ReadonlySet<string> = new Set()): Live {
  let changed = false;
  const runs: LiveRun[] = [];
  for (const r of l.runs) {
    if (r.open && hovered.has(r.runId)) {
      runs.push(r.touchedAt === now ? r : { ...r, touchedAt: now });
      changed ||= r.touchedAt !== now;
      continue;
    }
    if (r.open && r.ended && now - Math.max(r.ended.at, r.touchedAt) >= LINGER_MS) {
      runs.push({ ...r, open: false });
      changed = true;
      continue;
    }
    if (!r.open && r.ended && now - r.ended.at >= FORGET_MS) {
      changed = true;
      continue;
    }
    runs.push(r);
  }
  return changed ? { runs } : l;
}

export const openRuns = (l: Live): LiveRun[] => l.runs.filter((r) => r.open).slice(0, MAX_OPEN);
export const find = (l: Live, runId: string): LiveRun | undefined => l.runs.find((r) => r.runId === runId);

export function siteOf(url: string): string {
  const m = /^https?:\/\/([^/?#:]+)/i.exec(url);
  return m ? m[1].toLowerCase().replace(/^www\./, "") : "";
}

/** What it is doing, in the view's words: "Searching: history of tea", "Reading britannica.com". */
export function doingLine(text: string): string {
  return text
    .replace(/^Searching the web: /, "Searching: ")
    .replace(/^Fetching /, "Reading ")
    .replace(/^Helper: Searching the web: /, "Helper searching: ")
    .replace(/^Helper: Fetching /, "Helper reading ");
}

const STOPPED: Record<string, string> = { done: "Done", error: "Didn't finish", cancelled: "Stopped", rejected: "Stopped" };

export function endedLine(status: string): string {
  return STOPPED[status] ?? "Finished";
}

export function view(r: LiveRun): LiveView {
  const running = !r.ended;
  return {
    kind: "live",
    runId: r.runId,
    title: r.title || r.words || "Request",
    doing: running ? (r.doing ? doingLine(r.doing.text) : "Starting…") : endedLine(r.ended!.status),
    activity: running ? r.doing?.activity ?? null : null,
    sources: r.sources,
    notes: r.notes,
    written: r.written,
    hint: r.hint,
    running,
    ended: r.ended ? { status: r.ended.status, summary: r.ended.summary, answer: r.ended.status === "done" } : null,
    startedMs: r.startedMs,
  };
}

/** Plain text of what was found and written, for the view's Copy. */
export function plain(v: LiveView): string {
  const parts: string[] = [];
  if (v.written?.text) parts.push(v.written.text);
  if (v.notes.length) parts.push(v.notes.join("\n"));
  if (v.sources.length) parts.push(v.sources.map((s) => `${s.title || s.site} — ${s.url}`).join("\n"));
  return parts.join("\n\n");
}

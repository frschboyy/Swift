// How an answer reads on its card (ADR-017, the Capsule design). Pure: no DOM.
//
// - **Shape**: a one-line answer is shown large ("It's 3:42 pm"); a table gets the calendar
//   grid; a long one is clipped at six lines with "Read more"; anything else is paragraphs.
// - **Blocks**: paragraphs stay apart (a blank line or a new line starts one), "- " lines are a
//   list, and **bold**, *italic* and `code` are kept as marks. main.ts turns them into elements
//   with textContent only: answers are untrusted text, never HTML.
// - **Reading time**: how long an answer stays, ``clamp(4 s, words × 240 ms, 20 s)``.

import type { Idea, ResultDetails } from "./protocol";

export type Shape = "line" | "text" | "table" | "long";

/** A one-line answer this short or shorter is shown as display text. */
export const LINE_CHARS = 48;
export const READ_MIN_MS = 4000;
export const READ_MAX_MS = 20000;
export const MS_PER_WORD = 240;
const WORDS_PER_MINUTE = 200;

export function shape(summary: string, details: ResultDetails | null | undefined, long: boolean): Shape {
  if (long) return "long";
  if (details?.kind === "table") return "table";
  const flat = summary.trim();
  if (!details && flat.length <= LINE_CHARS && !flat.includes("\n")) return "line";
  return "text";
}

const words = (text: string): number => text.split(/\s+/).filter(Boolean).length;

/** How long an answer stays on screen (ms). */
export function readingMs(text: string): number {
  return Math.min(READ_MAX_MS, Math.max(READ_MIN_MS, words(text) * MS_PER_WORD));
}

/** "2 min read" for a long answer. */
export function minutesToRead(text: string): string {
  return `${Math.max(1, Math.ceil(words(text) / WORDS_PER_MINUTE))} min read`;
}

export type Mark = "b" | "i" | "code";
export type Run = { text: string; marks: Mark[] };
export type Block = { kind: "p"; runs: Run[] } | { kind: "ul"; items: Run[][] };

const LIST = /^\s*[-*•]\s+/;

/** Paragraphs and lists, with their inline marks. */
export function blocks(text: string): Block[] {
  const out: Block[] = [];
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line.trim()) continue;
    if (LIST.test(line)) {
      const last = out[out.length - 1];
      const item = inline(line.replace(LIST, ""));
      if (last?.kind === "ul") last.items.push(item);
      else out.push({ kind: "ul", items: [item] });
    } else {
      out.push({ kind: "p", runs: inline(line.trim().replace(/^#{1,6}\s+/, "")) });
    }
  }
  return out;
}

/** **bold**, *italic* / _italic_ and `code` within one line. Unmatched markers stay as text. */
export function inline(text: string): Run[] {
  const out: Run[] = [];
  const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*\s][^*]*)\*|(?<![\w])_([^_\s][^_]*)_(?![\w]))/g;
  let at = 0;
  for (const m of text.matchAll(pattern)) {
    if (m.index! > at) out.push({ text: text.slice(at, m.index), marks: [] });
    if (m[2] !== undefined) out.push({ text: m[2], marks: ["b"] });
    else if (m[3] !== undefined) out.push({ text: m[3], marks: ["code"] });
    else out.push({ text: m[4] ?? m[5], marks: ["i"] });
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at), marks: [] });
  return out;
}

// A diagram on a card is shrunk to fit at most this wide and this tall (styles.css .diagram-stage svg)...
export const DIAGRAM_CARD_PX = 260;
// ...but never so far that its smallest label drops below 10 px: one under Swift's smallest card text (the pick tag,
// 11 px), because at 11 even a four-step flow didn't fit a card; 15 physical px at 150% Windows scaling.
export const DIAGRAM_MIN_LABEL_PX = 10;

/** Whether a diagram drawn ``w`` by ``h`` with labels of ``labelPx`` stays readable shrunk into a card ``boxW``
 *  wide. If not, the card doesn't shrink it: it opens in full with Read more. */
export function diagramFits(w: number, h: number, labelPx: number, boxW: number): boolean {
  return labelPx * Math.min(1, boxW / w, DIAGRAM_CARD_PX / h) >= DIAGRAM_MIN_LABEL_PX;
}

/** Up to n card ideas, breadth-first so branches appear before deeper ideas. No child is kept without its parent. */
export function cardIdeas(children: Idea[], n: number): Set<Idea> {
  const kept = new Set<Idea>();
  for (let level = children; level.length && kept.size < n; level = level.flatMap((i) => i.children)) {
    for (const i of level.slice(0, n - kept.size)) kept.add(i);
  }
  return kept;
}

/** How a comparison's highlighted option is labelled: the worker's choice, never Swift's (B4 decision 4). */
export const PICK = "Worker's pick";

/** An answer's details as plain text: Copy, the reader's Copy, and screen readers' words for a shape. */
export function detailsText(details: ResultDetails | null | undefined): string {
  if (!details) return "";
  switch (details.kind) {
    case "text":
      return details.text;
    case "list":
      return details.items.map((i) => `- ${i}`).join("\n");
    case "table":
      return [details.columns, ...details.rows].map((r) => r.join("\t")).join("\n");
    case "compare":
      return [details.title, ["", ...details.items].join("\t"), ...details.rows.map((r) => [r.label, ...r.values].join("\t")),
        details.pick === undefined ? "" : `${PICK}: ${details.items[details.pick]}`, details.text].filter(Boolean).join("\n");
    case "diagram":
      return [details.title, details.source, details.text].filter(Boolean).join("\n");
    case "mindmap": {
      // One idea per line, indented by level: the map's words for Copy and screen readers.
      const lines = [details.root];
      const walk = (ideas: Idea[], depth: number): void => ideas.forEach((i) => { lines.push(`${"  ".repeat(depth - 1)}- ${i.label}`); walk(i.children, depth + 1); });
      walk(details.children, 1);
      return [details.title, ...lines, details.text].filter(Boolean).join("\n");
    }
    case "preview":
      return [
        details.title,
        details.file_type.toUpperCase(),
        details.pages ? `${details.pages} pages` : "",
        details.excerpt,
        details.text,
      ].filter(Boolean).join("\n");
  }
}

/** The text again, without marks (Copy, and the history line). */
export function plainText(text: string): string {
  return blocks(text)
    .map((b) => (b.kind === "p" ? b.runs.map((r) => r.text).join("") : b.items.map((i) => `- ${i.map((r) => r.text).join("")}`).join("\n")))
    .join("\n\n");
}

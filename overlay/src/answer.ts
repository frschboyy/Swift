// How an answer reads on its card (ADR-017, the Capsule design). Pure: no DOM.
//
// - **Shape**: a one-line answer is shown large ("It's 3:42 pm"); a table gets the calendar
//   grid; a long one is clipped at six lines with "Read more"; anything else is paragraphs.
// - **Blocks**: paragraphs stay apart (a blank line or a new line starts one), "- " lines are a
//   list, and **bold**, *italic* and `code` are kept as marks. main.ts turns them into elements
//   with textContent only: answers are untrusted text, never HTML.
// - **Reading time**: how long an answer stays, ``clamp(4 s, words × 240 ms, 20 s)``.

import type { ResultDetails } from "./protocol";

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

/** The text again, without marks (Copy, and the history line). */
export function plainText(text: string): string {
  return blocks(text)
    .map((b) => (b.kind === "p" ? b.runs.map((r) => r.text).join("") : b.items.map((i) => `- ${i.map((r) => r.text).join("")}`).join("\n")))
    .join("\n\n");
}

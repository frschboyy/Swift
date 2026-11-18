// Halo B13: a file list as a tree. Pure parts (no DOM): which rows show, and names cut in the middle.
import type { TreeEntry } from "./protocol";

/** A long name cut in the middle so its extension stays: "Quarterly report … final.xlsx". */
export function middleCut(name: string, max = 40): string {
  if (name.length <= max) return name;
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 && name.length - dot <= 8 ? name.slice(dot) : "";
  const keep = max - ext.length - 1;
  const head = Math.ceil(keep / 2);
  const stem = name.slice(0, name.length - ext.length);
  return `${stem.slice(0, head)}…${stem.slice(stem.length - (keep - head))}${ext}`;
}

export type Row = { entry: TreeEntry; depth: number; key: string };

/** The rows in view: a folder's entries show only while it's open (``open``: keys of open folders). */
export function visibleRows(entries: TreeEntry[], open: ReadonlySet<string>, depth = 0, prefix = ""): Row[] {
  return entries.flatMap((entry, i) => {
    const key = `${prefix}${i}`;
    const row = { entry, depth, key };
    return entry.folder && open.has(key) ? [row, ...visibleRows(entry.entries ?? [], open, depth + 1, `${key}/`)] : [row];
  });
}

/** The folders that start open: the ones the worker marked as answering the question. */
export function startOpen(entries: TreeEntry[], prefix = ""): string[] {
  return entries.flatMap((e, i) => {
    const key = `${prefix}${i}`;
    return e.folder ? [...(e.open ? [key] : []), ...startOpen(e.entries ?? [], `${key}/`)] : [];
  });
}

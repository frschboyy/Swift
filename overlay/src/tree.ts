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

/** B13: a row's path under the folder Swift verified, from its entries' names (the backend checks it again). Only a
 * row Swift found on disk has one; null otherwise (no Open, no Show in folder). */
export function pathOf(entries: TreeEntry[], key: string, root: string | undefined): string | null {
  if (!root) return null;
  const names: string[] = [];
  let level: TreeEntry[] | undefined = entries;
  let entry: TreeEntry | undefined;
  for (const i of key.split("/").map(Number)) {
    entry = level?.[i];
    if (!entry) return null;
    names.push(entry.name);
    level = entry.entries;
  }
  if (!entry?.found) return null;
  const sep = root.includes("/") && !root.includes("\\") ? "/" : "\\";
  return [root.replace(/[\\/]+$/, ""), ...names].join(sep);
}

export type TreeKey = "ArrowUp" | "ArrowDown" | "ArrowLeft" | "ArrowRight";

/** B13, keys in the reader: Up/Down move the selection; Right opens a folder (or steps into it), Left closes it
 * (or steps out to its folder). The selection and the open folders after the key. */
export function treeKey(rows: Row[], open: ReadonlySet<string>, selected: string | null, key: TreeKey): { selected: string | null; open: Set<string> } {
  const next = new Set(open);
  const at = rows.findIndex((r) => r.key === selected);
  const row = at >= 0 ? rows[at] : null;
  if (!row) return { selected: rows[0]?.key ?? null, open: next };
  if (key === "ArrowDown") return { selected: rows[Math.min(rows.length - 1, at + 1)].key, open: next };
  if (key === "ArrowUp") return { selected: rows[Math.max(0, at - 1)].key, open: next };
  if (key === "ArrowRight") {
    if (row.entry.folder && !next.has(row.key)) next.add(row.key);
    else if (row.entry.folder && rows[at + 1]?.depth === row.depth + 1) return { selected: rows[at + 1].key, open: next };
    return { selected: row.key, open: next };
  }
  if (row.entry.folder && next.has(row.key)) {
    next.delete(row.key);
    return { selected: row.key, open: next };
  }
  const parent = row.key.includes("/") ? row.key.slice(0, row.key.lastIndexOf("/")) : null;
  return { selected: parent ?? row.key, open: next };
}

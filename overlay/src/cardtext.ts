// A file change on a confirm card (X-17): the backend marks every line of the agent's text, so a line
// without the mark is always Swift's own. The mark becomes a bar down the whole line, because a character
// marks only the first row: a long line wrapping would put the agent's words at the edge, unmarked.

export const QUOTE = "│ ";

const FILE_CHANGES: ReadonlySet<string> = new Set(["Write", "Edit", "MultiEdit", "NotebookEdit"]);

export const hasMarkedLines = (tool: string): boolean => FILE_CHANGES.has(tool);

export type CardLine = { text: string; agent: boolean };

export function cardLines(detail: string): CardLine[] {
  return detail.split("\n").map((line) =>
    line.startsWith(QUOTE) ? { text: line.slice(QUOTE.length), agent: true } : { text: line, agent: false });
}

// B1: a command card leads with what the agent says the command is for (its own words, marked as its), then
// the command's first line, always in view, so a harmless-sounding sentence never sits over a command nobody
// sees (owner, 2026-11-14); only the rest is folded. With no such words the whole command shows, as before.
const COMMANDS: ReadonlySet<string> = new Set(["Bash", "PowerShell"]);

export const commandFolded = (tool: string, purpose: string | undefined): boolean =>
  COMMANDS.has(tool) && !!purpose?.trim();

/** The command's first line, always shown, and the rest, folded (empty for a one-line command). */
export function commandParts(detail: string): { head: string; rest: string } {
  const at = detail.indexOf("\n");
  return at < 0 ? { head: detail, rest: "" } : { head: detail.slice(0, at), rest: detail.slice(at + 1) };
}

// B2: a step card is a command card whose detail lists the step's commands, one a line. Approving covers
// each of them, so the list starts open: the owner sees what they approve without a click.
export const stepCommands = (tool: string, purpose: string | undefined, step: boolean | undefined, detail: string): string[] | null =>
  step && commandFolded(tool, purpose) ? detail.split("\n") : null;

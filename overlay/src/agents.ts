// Attribution text (ADR-008). The owner talks to Swift; the backend reports which
// provider is doing the work as a normalized `agent` + `activity`. This file is the
// only place that turns those into words, and it knows no provider by name.

import type { Activity, Agent } from "./protocol";

// What the working card says, without naming the provider (owner, 2026-10-26: no "Claude Code is
// thinking"; the result's byline says who did the work).
const DOING: Record<Activity, string> = {
  starting: "Working on it",
  reading: "Reading",
  searching: "Searching",
  editing: "Making changes",
  running: "Running a command",
  browsing: "Browsing",
  delegating: "Handing off a subtask",
  planning: "Planning",
  thinking: "Thinking",
  waiting: "Waiting",
  switching: "Switching models",
  blocked: "Blocked",
  working: "Working on it",
  writing: "Writing",
};

const isSwift = (agent: Agent | null | undefined): boolean => !agent || agent.id === "swift";

/** Working-card title: "Reading", "Writing in Word", "Thinking (helper)". */
export function activityLabel(_agent: Agent | null | undefined, activity: Activity | undefined, subagent = false, app?: string | null): string {
  if (activity === "writing") return `Writing${app ? ` in ${app}` : ""}`;
  const doing = DOING[activity ?? "working"] ?? DOING.working;
  return subagent ? `${doing} (helper)` : doing;
}

/** Before the provider reports anything. */
export function handoffLabel(_agent: Agent | null | undefined): string {
  return "Working on it";
}

/** Footer on results: Swift presents, the provider (if any) did the work. */
export function byline(agent: Agent | null | undefined): string {
  return isSwift(agent) ? "Swift" : `Swift · via ${agent!.name}`;
}

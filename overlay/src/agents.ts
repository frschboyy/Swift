// Attribution text (ADR-008). The owner talks to Swift; the backend reports which
// provider is doing the work as a normalized `agent` + `activity`. This file is the
// only place that turns those into words, and it knows no provider by name.

import type { Activity, Agent } from "./protocol";

const VERBS: Record<Activity, string> = {
  starting: "is starting",
  reading: "is reading",
  searching: "is searching",
  editing: "is making changes",
  running: "is running a command",
  browsing: "is browsing",
  delegating: "is handing off a subtask",
  planning: "is planning",
  thinking: "is thinking",
  waiting: "is waiting to retry",
  switching: "is switching models",
  blocked: "was blocked",
  working: "is working",
  writing: "is writing",
};

const isSwift = (agent: Agent | null | undefined): boolean => !agent || agent.id === "swift";

/** Working-card title: "Claude Code is reading", "Swift is writing in Word", or Swift's own coordination. */
export function activityLabel(agent: Agent | null | undefined, activity: Activity | undefined, subagent = false, app?: string | null): string {
  // Starting up isn't news (owner, 2026-10-26): the next steps and the byline say who does the work.
  if (activity === "starting") return handoffLabel(agent);
  if (isSwift(agent)) return activity === "writing" ? `Swift is writing${app ? ` in ${app}` : ""}` : "Swift is coordinating";
  const who = subagent ? `${agent!.name}’s helper` : agent!.name;
  return `${who} ${VERBS[activity ?? "working"] ?? VERBS.working}`;
}

/** Before the provider reports anything. No provider name yet: its own steps ("Claude Code is reading") and the result's byline give it. */
export function handoffLabel(_agent: Agent | null | undefined): string {
  return "Working on it";
}

/** Footer on results: Swift presents, the provider (if any) did the work. */
export function byline(agent: Agent | null | undefined): string {
  return isSwift(agent) ? "Swift" : `Swift · via ${agent!.name}`;
}

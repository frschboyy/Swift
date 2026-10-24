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
};

const isSwift = (agent: Agent | null | undefined): boolean => !agent || agent.id === "swift";

/** Working-card title: "Claude Code is reading", or Swift's own coordination. */
export function activityLabel(agent: Agent | null | undefined, activity: Activity | undefined, subagent = false): string {
  if (isSwift(agent)) return "Swift is coordinating";
  const who = subagent ? `${agent!.name}’s helper` : agent!.name;
  return `${who} ${VERBS[activity ?? "working"] ?? VERBS.working}`;
}

/** Before the provider reports anything: Swift has handed the request over. */
export function handoffLabel(agent: Agent | null | undefined): string {
  return isSwift(agent) ? "Swift is working" : `Swift handed this to ${agent!.name}`;
}

/** Footer on results: Swift presents, the provider (if any) did the work. */
export function byline(agent: Agent | null | undefined): string {
  return isSwift(agent) ? "Swift" : `Swift · via ${agent!.name}`;
}

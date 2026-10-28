// What the owner is told when Swift's engine (the Python backend) can't run, and the way back:
// "Restart Swift" on the card, the same as the tray's (audit 2026-10, B-04). Rust ends the old
// engine and everything it started before a new one starts (backend.rs `restart`).

export type EngineProblem = {
  title: string;
  message: string;
  hint?: string;
  detail?: string | null;
  // The card offers Restart Swift.
  restart: true;
};

export function describeBackendProblem(problem: string): EngineProblem {
  if (problem.startsWith("config ")) {
    return {
      title: "There's a problem in config.yaml",
      message: "Swift couldn't read its settings, so it can't start.",
      hint: "Fix the setting shown in the details, then restart Swift.",
      detail: problem.slice("config ".length),
      restart: true,
    };
  }
  if (problem.includes("could not start the backend")) {
    return {
      title: "Swift couldn't start",
      message: "Its speech and agent engine didn't launch.",
      hint: "Check the Python setup in the README (`uv sync`), then restart Swift.",
      detail: problem,
      restart: true,
    };
  }
  if (problem.includes("session token")) {
    return {
      title: "Swift lost its connection",
      message: "The overlay and Swift's engine stopped trusting each other.",
      hint: "Restart Swift here or from the tray icon.",
      detail: problem,
      restart: true,
    };
  }
  return {
    title: "Swift's engine stopped",
    message: "The part of Swift that listens and runs requests stopped unexpectedly.",
    hint: "Restart Swift here or from the tray icon. The logs say what happened.",
    detail: problem,
    restart: true,
  };
}

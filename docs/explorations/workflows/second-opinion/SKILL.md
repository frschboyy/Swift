---
name: second-opinion
description: Make a code change with one coding agent, then have a different agent review the diff before the user decides whether to keep it. Use when the user asks for a change "with a second opinion", "and have it reviewed", or "check it with Codex".
license: MIT
metadata:
  swift-manifest: swift.yaml
---

# Second opinion

1. Make the requested change in the project, on a new branch. Run the tests that cover it.
2. Hand the diff (not the conversation) to a second agent from a different provider. Ask it for correctness problems only: bugs, missed cases, broken tests. No style comments.
3. Show the user the review next to the diff summary.
4. If the review found problems, offer to fix them with the first agent. Don't merge or push anything; the user decides.

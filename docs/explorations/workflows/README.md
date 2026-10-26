# Example workflows (ADR-011 exploration)

These test the package format proposed in ADR-011 against real tasks. Swift doesn't load or run them; nothing here is wired up.

Each folder is one workflow:

| File | For | Required |
|---|---|---|
| `SKILL.md` | The playbook, in the open Agent Skills format: any agent that supports skills (Claude Code, Codex, Hermes, ...) can follow it as written | yes |
| `swift.yaml` | Swift's manifest: how to start it, its inputs, the capabilities it needs, and what it shows | yes |
| `recipe.yaml` | The hardened version: steps Swift runs itself, with agent steps only where judgment is needed | no |
| `tests/` | Example runs with fake tools, checked when the workflow or a tool changes | no |

| Workflow | Shape | Shows |
|---|---|---|
| [research-brief](research-brief/) | playbook only | an agent-driven workflow; files written only inside an allowed folder |
| [tidy-downloads](tidy-downloads/) | recipe | deterministic steps, one agent step for the leftovers, a batch confirm, undo |
| [lecture-digest](lecture-digest/) | recipe, on a schedule | a trigger other than voice; reading local files; nothing external |
| [email-someone](email-someone/) | recipe | ADR-010's email flow as a recipe: Swift's tools plus one writing step |
| [second-opinion](second-opinion/) | recipe | coordinating two providers: one makes a change, another reviews it |

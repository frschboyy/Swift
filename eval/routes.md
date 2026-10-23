# Route and demand labels (ADR-007)

`eval/routes.jsonl` holds one labeled request per line. It scores the router: the rules, the local classifier and the demand estimate (ADR-007 §8, step 1). Score a router with `spikes/routing/eval_routes.py`.

## Fields

| Field | Values | Meaning |
|---|---|---|
| `id` | string | Stable id. Items relabeled from `utterances.jsonl` keep their id. New ones use `rq…` (Swift-style requests from `spikes/stt/prompts.txt`) or `nw…` (written for this set). |
| `text` | string | The request as transcribed: no fixes for disfluency, "Hey Swift" left in. |
| `route` | `control`, `local`, `claude` | Where it should go (below). |
| `demand` | `light`, `standard`, or `null` | Only for `route: claude`. What it should start on (below). |
| `override` | `opus`, `haiku`, or absent | The request names a model ("use opus …", "think hard …"). The rules strip the prefix and force that model. |
| `tags` | list | Free-form: `planned` (needs a handler Swift doesn't have yet), `followup`, `no-tool` (Claude Code has no way to do it here), `edit`, `destructive`, `compound`, plus the original v2 tags. |
| `split` | `train` or `test` | Fixed. Paraphrases of one request (canonical, `stt` lowercase, "Hey Swift" variants) always share a split. |
| `source` | `v2`, `prompts`, `new` | Where the item came from. |

## Routes

- **`control`**: acts on Swift itself, not on the world. Stop, cancel, never mind, forget that, mute, yes/no and approve/reject (an open confirm card), repeat that, "what can you do".
- **`local`**: Swift answers without a model. Time and date now. Opening an app, a folder or a project in VS Code are `local` with the `planned` tag (ADR-007 §3). A request that also asks for more ("open my project **and run the tests**") is `claude`.
- **`claude`**: everything else, including requests Swift has no tool for (calendar, reminders, sending email, weather, music: tag `no-tool`). Owner decision 3: Claude Code tries them.

## Demand (`route: claude` only)

The question is: **would Haiku do this well without needing to escalate?**

- **`light`**: questions, explanations, translation, drafting short text (emails, notes); reading, listing, searching or summarizing files; running one command and reporting the result (tests, `git log`, disk space, outdated packages); one simple edit to a text or config file ("set the beam size to three"); a single git command (commit, new branch); requests it can only decline (`no-tool`).
- **`standard`**: changing code; investigating a problem ("why is…", "find out what's slow"); debugging a failure; anything multi-step that needs judgment (cleaning up a folder, comparing approaches by running them); follow-ups that refer to earlier work ("now commit it", "do the same for the other file"), since that context has to be rebuilt from the repo.
- **When unsure, `standard`.** Under-estimating costs an escalation. Over-estimating only costs money, and the router does the same: an unsure demand starts on Sonnet.

Destructive requests ("delete the old drafts folder") are labeled by demand like any other. The confirm card is what makes them safe, not the model.

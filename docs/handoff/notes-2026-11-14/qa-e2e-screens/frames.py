"""Frames for the harness from Swift's own code: the long answer (split_answer via outcome_for), B1's command
card (confirm_card + command_purpose), and B2's step card and a listed delete's own card (the real executor)."""
import asyncio, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "tests/unit")
from swift.executors.claude_mapping import confirm_card, command_purpose, outcome_for
from test_claude_mapping import TEA_OPENING
import test_b2_step_grant as b2

out = {}
parts = "".join(f"\n\n## Part {i}\nSection {i} of the history: traders, ships and gardens carried the leaf further, and each place made the drink its own way." for i in range(1, 9))
answer = TEA_OPENING + parts + "\n\n## Today\nTHE-END-MARKER: tea is the second most drunk drink after water."
o = outcome_for({"type": "result", "subtype": "success", "result": answer})
out["long"] = {"summary": o.summary, "details": o.details}
said = "Creates a repository called notes on your GitHub, so it can be copied to this PC."
args = {"command": "gh repo create notes --private\ncd notes\ngit status", "description": said}
t, d = confirm_card("Bash", args)
out["b1"] = {"title": t, "detail": d, "purpose": command_purpose("Bash", args)}

async def step():
    ex, run = b2._executor(Path(tempfile.mkdtemp()))
    card, said2 = await b2._approve_step(ex, run, [*b2.COMMANDS, "rm old-notes.md"])
    out["b2"] = {"title": card.text, "detail": card.detail, "purpose": card.purpose, "step": card.step, "said": said2}
    from claude_agent_sdk import PermissionResultAllow
    asking = asyncio.create_task(ex._ask(run, "cc-1", "Bash", {"command": "rm old-notes.md", "description": "Removes the old notes file."}))
    c = await asyncio.wait_for(run.queue.get(), 5)
    out["delete"] = {"title": c.text, "detail": c.detail, "purpose": c.purpose, "step": bool(c.step)}
    await ex.reply(c.request_id, False); await asyncio.wait_for(asking, 5)
asyncio.run(step())
print(json.dumps(out, ensure_ascii=False, indent=1))

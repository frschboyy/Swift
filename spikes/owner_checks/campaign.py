"""A test campaign: work through the owner checks against one build, one check at a time.

Usage (from the repo root; the /campaign command drives it):
  python spikes/owner_checks/campaign.py begin NAME [--commit SHA]   freeze the build Swift runs (default main)
  python spikes/owner_checks/campaign.py next                        the next check, its setup and steps
  python spikes/owner_checks/campaign.py start ID                    note the time the check starts
  python spikes/owner_checks/campaign.py done                        what the logs saw since start (report.py)
  python spikes/owner_checks/campaign.py verdict ID pass|rough|fail|blocked|retired --note "…"
  python spikes/owner_checks/campaign.py end                         close the campaign

While a campaign is open, plan.py measures staleness up to its commit only, so a result can't go stale
under the owner. A pass in a campaign retires the check: its text moves to owner-checks-archive.md and its
results stay in the ledger. rough (works, not good enough) and fail stay open with the owner's note.
The time window and the full report are kept on this PC, in %LOCALAPPDATA%\\Swift\\campaign\\ (they hold
the owner's words); the ledger gets the verdict, the window and the note.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import plan

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Swift"
WORK = LOCAL / "campaign"
OPEN = WORK / "open.json"
SKIP = ("done", "retired", "blocked", "passive", "failing", "rough")  # nothing to learn from running these now
ARCHIVE_HEAD = """# Owner checks: the archive

Checks that passed in a test campaign, or were retired as obsolete, moved here from
[`owner-checks.md`](owner-checks.md) by `spikes/owner_checks/campaign.py`. Every result, its time window and the
owner's notes are in `owner-checks-ledger.yaml`. A retired check doesn't come back when its code changes; new
behaviour gets a new check.
"""


def current(led: dict) -> dict:
    c = led.get("campaign")
    if not c:
        raise SystemExit("No campaign is open: start one with `campaign.py begin NAME`.")
    return c


def begin(name: str, commit: str) -> None:
    text = plan.LEDGER.read_text(encoding="utf-8")
    if re.search(r"^campaign:", text, re.M):
        raise SystemExit("A campaign is already open: `campaign.py end` closes it.")
    sha = plan.git("rev-parse", "--short", commit).strip()
    block = (f"# campaign: the build the owner tests while it's open (campaign.py). Results can't go stale under it,\n"
             f"#         and a pass in it retires the check.\ncampaign:\n  name: {name}\n  commit: {sha}\n"
             f"  started: '{datetime.now():%Y-%m-%d %H:%M}'\n\n")
    plan.LEDGER.write_text(text.replace("\nruns:", "\n" + block + "runs:", 1), encoding="utf-8", newline="\n")
    print(f"Campaign {name} is open at {sha}. Run Swift from that commit until it ends.")


def end() -> None:
    text = plan.LEDGER.read_text(encoding="utf-8")
    new = re.sub(r"^# campaign:.*\n#.*\ncampaign:\n(?:  .*\n)+\n?", "", text, flags=re.M)
    if new == text:
        raise SystemExit("No campaign is open.")
    plan.LEDGER.write_text(new, encoding="utf-8", newline="\n")
    print("Campaign closed. Its results stay in the ledger; plan.py measures staleness against main again.")


def queue(states: list[plan.State], runs: list[dict], name: str) -> list[plan.State]:
    """What's left to run: a section at a time, the most urgent section first, checks in the file's order,
    a check another builds on before it. A check with a verdict in this campaign is out."""
    had = {str(i) for r in runs if r.get("campaign") == name for ids in r["checks"].values() for i in ids}
    left = [s for s in states if s.kind not in SKIP and s.check.id not in had and s.check.file == plan.CHECKS.name]
    order = {s.check.id: i for i, s in enumerate(states)}
    urgency: dict[str, float] = {}
    for s in left:
        urgency[s.check.section] = max(urgency.get(s.check.section, 0), s.score)
    first: dict[str, int] = {}
    for s in left:
        first.setdefault(s.check.section, order[s.check.id])
    left.sort(key=lambda s: (-urgency[s.check.section], first[s.check.section], order[s.check.id]))
    by_id = {s.check.id: s for s in left}
    out: list[plan.State] = []
    for s in left:
        for need in s.check.needs:
            if need in by_id and by_id[need] not in out:
                out.append(by_id[need])
        if s not in out:
            out.append(s)
    return out


def blocks(text: str) -> list[tuple[str, int, int]]:
    """(id, start, end) of each check's text, up to the next check or heading."""
    marks = [(m.group(1), m.start()) for m in plan.ANCHOR.finditer(text)]
    heads = [m.start() for m in re.finditer(r"^#{2,3} ", text, re.M)]
    out = []
    for cid, at in marks:
        nxt = min([p for _, p in marks if p > at] + [h for h in heads if h > at] + [len(text)])
        out.append((cid, at, nxt))
    return out


def setup(text: str, section: str) -> str:
    """A section's own words before its first check: what to set up, how long it takes."""
    m = re.search(rf"^### {re.escape(section)}\n(.*?)(?=^<a id=|^#{{2,3}} )", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def archive(cids: list[str]) -> None:
    """Move each check's text from owner-checks.md into the archive, under its section; a section left
    with no checks moves its heading and setup too."""
    text = plan.CHECKS.read_text(encoding="utf-8")
    arch = plan.ARCHIVE.read_text(encoding="utf-8") if plan.ARCHIVE.exists() else ARCHIVE_HEAD
    checks = plan.parse_checks(text)
    for cid in cids:
        if cid not in checks:
            continue
        section = checks[cid].section
        span = next((a, b) for i, a, b in blocks(text) if i == cid)
        body = text[span[0]:span[1]].rstrip() + "\n"
        if f"\n### {section}\n" not in arch:
            arch = arch.rstrip() + f"\n\n### {section}\n\n" + (setup(text, section) + "\n\n" if setup(text, section) else "")
        head = arch.index(f"\n### {section}\n") + len(f"\n### {section}\n")
        nxt = re.search(r"^#{2,3} ", arch[head:], re.M)
        at = head + nxt.start() if nxt else len(arch)
        arch = arch[:at].rstrip() + "\n\n" + body + ("\n" if nxt else "") + arch[at:]
        text = text[:span[0]] + text[span[1]:]
        if not any(c.section == section for c in plan.parse_checks(text).values()):
            text = re.sub(rf"^### {re.escape(section)}\n.*?(?=^#{{2,3}} |\Z)", "", text, count=1, flags=re.M | re.S)
    plan.CHECKS.write_text(text, encoding="utf-8", newline="\n")
    plan.ARCHIVE.write_text(arch.rstrip() + "\n", encoding="utf-8", newline="\n")


def assess(checks: dict[str, plan.Check], led: dict) -> list[plan.State]:
    """plan.compute without the open branches (a git call per branch: half a minute on this PC)."""
    today = datetime.now()
    end_at = str(current(led)["commit"])
    since = {sha: plan.commits(f"{sha}..{end_at}") for sha in {str(r["commit"]) for r in led["runs"]}}
    recent = plan.commits(f"--since={today - plan.timedelta(days=plan.RECENT_DAYS):%Y-%m-%d}", end_at)
    return plan.assess(checks, led["runs"], since, recent, plan.births(), today)


def show_next(limit: int = 1) -> None:
    checks, led = plan.load()
    c = current(led)
    states = assess(checks, led)
    left = queue(states, led["runs"], c["name"])
    mine = [r for r in led["runs"] if r.get("campaign") == c["name"]]
    tally = {k: sum(len(r["checks"].get(k, [])) for r in mine) for k in ("PASS", "ROUGH", "FAIL", "BLOCKED", "RETIRED")}
    print(f"Campaign {c['name']} at {c['commit']}: " + ", ".join(f"{v} {k.lower()}" for k, v in tally.items())
          + f"; {len(left)} to go.")
    moved = [m for m in plan.commits(f"{c['commit']}..main") if any(f.startswith(plan.CODE) for f in m.files)]
    if moved:
        print(f"Warning: main has {len(moved)} code change(s) since the campaign's build (such as `{moved[0].sha}`). "
              "If Swift was restarted from main, it isn't the build under test.")
    if not left:
        print("Nothing left to run in this campaign.")
        return
    text = plan.CHECKS.read_text(encoding="utf-8")
    for s in left[:limit]:
        k = s.check
        print(f"\n### {k.section}\n")
        if (st := setup(text, k.section)):
            print(st + "\n")
        if k.needs:
            print(f"(Builds on check {', '.join(k.needs)}: do its steps first if it isn't fresh on screen.)\n")
        print(f"Why now: {s.why}.\n")
        print(k.text.strip())


def start(cid: str) -> None:
    checks, led = plan.load()
    current(led)
    if cid not in checks:
        raise SystemExit(f"No check {cid}.")
    WORK.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    OPEN.write_text(json.dumps({"check": cid, "start": f"{now:%Y-%m-%d %H:%M}"}), encoding="utf-8")
    print(f"Check {cid} started at {now:%H:%M}.")


def opened() -> dict:
    if not OPEN.exists():
        raise SystemExit("No check is started: `campaign.py start ID` first.")
    return json.loads(OPEN.read_text(encoding="utf-8"))


def done() -> None:
    o = opened()
    checks, led = plan.load()
    c = current(led)
    day, hm = o["start"].split()
    env = {**os.environ, "PYTHONPATH": str(plan.ROOT / "src")}
    out = subprocess.run([sys.executable, str(Path(__file__).parent / "report.py"), "--since", hm, "--date", day],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=plan.ROOT)
    report = out.stdout + out.stderr
    end_at = datetime.now()
    folder = WORK / c["name"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{o['check']}-{o['start'].replace('-', '').replace(' ', '-').replace(':', '')}.txt"
    path.write_text(report, encoding="utf-8")
    OPEN.write_text(json.dumps({**o, "end": f"{end_at:%Y-%m-%d %H:%M}", "evidence": path.name}), encoding="utf-8")
    # shortcut: the window starts on the minute, so a request in the minute before the start can show; fine one check at a time.
    requests = report.split("\nChecks (", 1)[0].strip()
    mine = [ln for ln in report.splitlines()
            if (m := re.match(r"^\s*(PASS|FAIL|NOT SEEN|LOOK)\s+(.+?)(?:\s{3}\(.*)?$", ln))
            and o["check"] in plan.report_ids(m.group(2), checks)]
    print(f"Check {o['check']}, {o['start'][11:]} to {end_at:%H:%M}. Full report: {path}\n")
    print(requests + "\n")
    print("What the report says about this check:" if mine else "The report has no line for this check: only your eyes can tell.")
    for ln in mine:
        print(ln)


def verdict(cid: str, outcome: str, note: str) -> None:
    checks, led = plan.load()
    c = current(led)
    outcome = outcome.upper()
    if outcome not in ("PASS", "ROUGH", "FAIL", "BLOCKED", "RETIRED") or cid not in checks:
        raise SystemExit("verdict needs a check id and one of pass, rough, fail, blocked, retired")
    o = json.loads(OPEN.read_text(encoding="utf-8")) if OPEN.exists() else {}
    run: dict = {"date": o.get("start") or f"{datetime.now():%Y-%m-%d %H:%M}", "commit": c["commit"], "source": "owner",
                 "campaign": c["name"]}
    if o.get("check") == cid:
        run["window"] = f"{o['start']} to {o.get('end', f'{datetime.now():%Y-%m-%d %H:%M}')[11:]}"
        if o.get("evidence"):
            run["evidence"] = o["evidence"]
    if note:
        run["note"] = note
    run["checks"] = {outcome: [cid]}
    plan.append_run(run)
    if outcome in ("PASS", "RETIRED"):
        archive([cid])
    if o.get("check") == cid:
        OPEN.unlink()
    print(f"Check {cid}: {outcome.lower()}" + (", moved to the archive." if outcome in ("PASS", "RETIRED") else ", stays open."))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin")
    b.add_argument("name")
    b.add_argument("--commit", default="main")
    n = sub.add_parser("next")
    n.add_argument("--count", type=int, default=1)
    s = sub.add_parser("start")
    s.add_argument("id")
    sub.add_parser("done")
    v = sub.add_parser("verdict")
    v.add_argument("id")
    v.add_argument("outcome")
    v.add_argument("--note", default="")
    sub.add_parser("end")
    a = ap.parse_args()
    if a.cmd == "begin":
        begin(a.name, a.commit)
    elif a.cmd == "next":
        show_next(a.count)
    elif a.cmd == "start":
        start(a.id)
    elif a.cmd == "done":
        done()
    elif a.cmd == "verdict":
        verdict(a.id, a.outcome, a.note)
    else:
        end()


if __name__ == "__main__":
    main()

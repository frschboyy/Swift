"""Owner checks roadmap: what to run next, and where every check stands.

Usage (from the repo root):
  uv run python spikes/owner_checks/plan.py                  print the roadmap
  uv run python spikes/owner_checks/plan.py --write          also rewrite its two blocks in owner-checks.md
  uv run python spikes/owner_checks/plan.py --record FILE    add a pasted report.py output to the ledger
  uv run python spikes/owner_checks/plan.py --set 216=pass 217=fail --note "the tail had a gap at 150%"

It reads docs/testing/owner-checks.md (the checks), docs/testing/owner-checks-ledger.yaml (what each
check proves, and every result) and git (what changed since each result, and the open branches).
A check ranks higher when it failed and its code changed since, when it is new or changed and was
never run, and when it guards a product rule. It changes nothing but the ledger and the two blocks.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ROOT / "docs" / "testing" / "owner-checks.md"
LEDGER = ROOT / "docs" / "testing" / "owner-checks-ledger.yaml"
CODE = ("src/swift/", "overlay/src/", "overlay/src-tauri/src/")
RECENT_DAYS = 14
VERDICTS = ("PASS", "FAIL", "PARTIAL", "RETIRED", "BLOCKED")
FINDING = re.compile(r"\b[A-Z]-\d{2}\b")
ANCHOR = re.compile(r'<a id="check-([^"]+)"></a>')


@dataclass
class Check:
    id: str
    title: str
    section: str
    text: str
    areas: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)

    @property
    def num(self) -> int:
        return int(re.match(r"\d+", self.id).group())  # type: ignore[union-attr]

    @property
    def first_step(self) -> str:
        m = re.search(r"^1\. (.*)$", self.text, re.M)
        return m.group(1) if m else ""

    @property
    def passive(self) -> bool:
        """It can't be run on demand: the report sees it when it happens."""
        return self.first_step.startswith(("Nothing to do", "Skip this one"))

    @property
    def conditional(self) -> bool:
        return self.first_step.startswith("Only if")

    @property
    def needs(self) -> list[str]:
        """Checks its first step builds on ("After check 17", "With check 168's two running")."""
        return [n for n in re.findall(r"\bchecks? (\d+[a-z]?)\b", self.first_step) if n != self.id]

    @property
    def findings(self) -> set[str]:
        return set(FINDING.findall(self.section + " " + self.text))


def parse_checks(text: str) -> dict[str, Check]:
    out: dict[str, Check] = {}
    section = ""
    parts = re.split(r"^(### .*)$", text, flags=re.M)
    for part in parts:
        if part.startswith("### "):
            section = part[4:].strip()
            continue
        bits = ANCHOR.split(part)
        for i in range(1, len(bits), 2):
            cid, body = bits[i], bits[i + 1]
            head = body.split("\n", 1)[0]
            title = re.sub(r"^\*\*Check [^*.]+\.?\s*|\*\*$", "", head).strip()
            out[cid] = Check(cid, title, section, body)
    return out


def expand(spec: list[object], known: dict[str, Check]) -> list[str]:
    """[1, 2b, '43-48'] -> ids; a range takes every id whose number is in it (19b in 18-20)."""
    ids: list[str] = []
    for item in spec:
        s = str(item)
        m = re.fullmatch(r"(\d+)-(\d+)", s)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            ids += [c.id for c in known.values() if lo <= c.num <= hi]
        else:
            ids.append(s)
    return ids


def load(text: str | None = None, ledger: dict | None = None) -> tuple[dict[str, Check], dict]:
    checks = parse_checks(text if text is not None else CHECKS.read_text(encoding="utf-8"))
    led = ledger if ledger is not None else yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    for name, area in led["areas"].items():
        for cid in expand(area["checks"], checks):
            if cid in checks:
                c = checks[cid]
                c.areas.append(name)
                c.paths += area["paths"]
                if area.get("rule"):
                    c.rules.append(area["rule"])
    for f in led.get("focus") or []:
        for cid in expand(f["checks"], checks):
            if cid in checks:
                checks[cid].focus.append(f["why"])
    led["runs"] = led.get("runs") or []
    return checks, led


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


@dataclass
class Commit:
    sha: str
    date: str
    subject: str
    message: str
    files: list[str]


def commits(*rev: str) -> list[Commit]:
    """Newest first, with the files each touched (merges count through their own commits)."""
    out: list[Commit] = []
    raw = git("log", "--no-merges", "--format=%x1e%h%x1f%cs%x1f%s%x1f%B%x1f", "--name-only", *rev)
    for rec in raw.split("\x1e")[1:]:
        sha, date, subject, body, files = rec.split("\x1f")
        out.append(Commit(sha, date, subject, body, [f for f in files.split("\n") if f.strip()]))
    return out


def births() -> dict[str, str]:
    """The day each check id first appeared in owner-checks.md (table rows, then numbered headings)."""
    born: dict[str, str] = {}
    raw = git("log", "--reverse", "--first-parent", "-m", "-p", "-U0", "--format=%x1e%cs", "main", "--", "docs/testing/owner-checks.md")
    for rec in raw.split("\x1e")[1:]:
        day, _, diff = rec.partition("\n")
        for cid in re.findall(r'^\+(?:\| (\d+[a-z]?) \||<a id="check-([^"]+)">)', diff, re.M):
            born.setdefault(cid[0] or cid[1], day)
    return born


def named(c: Check, commit: Commit) -> bool:
    """The commit's message names the check, or a finding the check names."""
    names = re.findall(r"\bchecks? ((?:\d+[a-z]?(?:[–-]\d+)?(?:, | and )?)+)", commit.message, re.I)
    for group in names:
        for lo, hi in re.findall(r"(\d+[a-z]?)(?:[–-](\d+))?", group):
            if c.id == lo or (hi and lo.isdigit() and int(lo) <= c.num <= int(hi)):
                return True
    return bool(c.findings & set(FINDING.findall(commit.message)))


def touches(c: Check, commit: Commit) -> bool:
    """The commit changed what the check sees: it touched code, and that code or its message is the check's."""
    if not any(f.startswith(CODE) for f in commit.files):  # docs, tests and spikes change no behaviour
        return False
    return named(c, commit) or any(fnmatch(f, p) for f in commit.files for p in c.paths)


@dataclass
class State:
    check: Check
    kind: str  # a key of LABEL
    last: dict | None
    changes: list[Commit]
    score: float = 0.0
    why: str = ""
    born: str = ""


LABEL = {
    "fixed": "Changed since it failed: run it again",
    "never": "Never run",
    "partial": "Partly seen",
    "stale": "Passed, changed since",
    "passed": "Passed, nothing changed since",
    "failing": "Failed, waiting for a fix",
    "passive": "Only when it happens: the report watches for it",
    "retired": "Retired",
    "blocked": "Blocked",
}


def last_result(cid: str, runs: list[dict]) -> dict | None:
    for run in sorted(runs, key=lambda r: str(r["date"]), reverse=True):
        for outcome, ids in (run.get("checks") or {}).items():
            if cid in [str(i) for i in ids]:
                return {**run, "outcome": outcome}
    return None


def assess(checks: dict[str, Check], runs: list[dict], since: dict[str, list[Commit]],
           recent: list[Commit], born: dict[str, str], today: datetime) -> list[State]:
    cutoff = f"{today - timedelta(days=RECENT_DAYS):%Y-%m-%d}"
    states: list[State] = []
    for c in checks.values():
        last = last_result(c.id, runs)
        changes = [m for m in since.get(str(last["commit"]), []) if touches(c, m)] if last else []
        new = [m for m in recent if touches(c, m)]
        outcome = last["outcome"] if last else None
        if outcome in ("RETIRED", "BLOCKED"):
            kind = outcome.lower()
        elif outcome == "FAIL":
            kind = "fixed" if changes else "failing"
        elif c.passive:
            kind = "passive"
        elif outcome == "PASS":
            kind = "stale" if changes else "passed"
        elif outcome == "PARTIAL":
            kind = "partial"
        else:
            kind = "never"
        s = State(c, kind, last, changes if last else new, born=born.get(c.id, ""))
        fresh = s.born >= cutoff
        base = {"fixed": 110, "partial": 55, "never": 85 if fresh else 60 if new else 40,
                "stale": 50 + 2 * min(len(changes), 5)}.get(kind, 0)
        s.score = base * (0.5 if c.conditional else 1) + (15 if base and c.rules else 0) + (20 if base and c.focus else 0)
        s.why = reason(s, today, fresh)
        states.append(s)
    return states


def reason(s: State, today: datetime, fresh: bool) -> str:
    when = f"on {str(s.last['date'])[:10]}" if s.last else ""
    n = len(s.changes)
    # the change to show: one that names the check or its finding, else the newest
    shown = next((m for m in s.changes if named(s.check, m)), s.changes[0]) if s.changes else None
    latest = f" (such as `{shown.sha}` {shown.subject})" if shown else ""
    text = {
        "fixed": f"failed {when}; {n} change{'s' * (n != 1)} since{latest}",
        "never": f"new on {s.born}, never run" if fresh else
                 f"never run; its code changed {n} time{'s' * (n != 1)} in {RECENT_DAYS} days{latest}" if n else "never run",
        "partial": f"partly seen {when}: some of it only you can tell" + (f"; {n} change{'s' * (n != 1)} since" if n else ""),
        "stale": f"passed {when}; {n} change{'s' * (n != 1)} since{latest}",
    }.get(s.kind, LABEL[s.kind])
    if s.check.rules:
        text += f"; product rule: {s.check.rules[0]}"
    if s.check.focus:
        text += f"; asked for: {s.check.focus[0]}"
    if s.check.conditional:
        text += "; only if it applies to you"
    return text


def run_list(states: list[State], limit: int) -> list[State]:
    by_id = {s.check.id: s for s in states}
    picked: list[State] = []
    for s in sorted((s for s in states if s.score > 0), key=lambda s: (-s.score, s.born and -int(s.born.replace("-", "")), -len(s.changes), s.check.num)):
        if len(picked) >= limit:
            break
        for need in s.check.needs:  # a check that builds on another runs after it
            if need in by_id and by_id[need] not in picked:
                picked.append(by_id[need])
        if s not in picked:
            picked.append(s)
    return picked


def branch_view(checks: dict[str, Check]) -> list[tuple[str, list[str], list[str]]]:
    """(branch, its new check ids, checks on main whose code it changes) for each unmerged branch."""
    out = []
    for b in git("branch", "--no-merged", "main", "--format=%(refname:short)").split():
        if b.startswith("backup/"):
            continue
        try:
            theirs = parse_checks(git("show", f"{b}:docs/testing/owner-checks.md"))
        except subprocess.CalledProcessError:
            theirs = {}
        files = git("diff", "--name-only", f"main...{b}").split()
        hit = [c.id for c in checks.values() if any(fnmatch(f, p) for f in files for p in c.paths)]
        new = [i for i in theirs if i not in checks]
        if new or hit:
            out.append((b, new, hit))
    return out


def gaps(led: dict, recent: list[Commit]) -> list[tuple[str, int]]:
    """Code changed in the last RECENT_DAYS days that no area owns."""
    owned = [p for a in led["areas"].values() for p in a["paths"]] + [i["path"] for i in led.get("ignore", [])]
    count: dict[str, int] = {}
    for m in recent:
        for f in m.files:
            if f.startswith(CODE) and not f.endswith((".test.ts", "_test.rs")) and not any(fnmatch(f, p) for p in owned):
                count[f] = count.get(f, 0) + 1
    return sorted(count.items(), key=lambda kv: -kv[1])


def dangling(checks: dict[str, Check]) -> list[tuple[str, str]]:
    """Docs that name a check that isn't in owner-checks.md."""
    out = []
    for path in [ROOT / "CLAUDE.md", *sorted((ROOT / "docs" / "handoff").glob("*.md")),
                 *sorted((ROOT / "docs" / "decisions").glob("*.md"))]:
        for n in re.findall(r"\b[Cc]hecks? (\d{1,3}[a-z]?)\b", path.read_text(encoding="utf-8")):
            if n not in checks:
                out.append((str(path.relative_to(ROOT)).replace("\\", "/"), n))
    return sorted(set(out))


def link(c: Check) -> str:
    return f"[{c.id}](#check-{c.id})"


def name(c: Check) -> str:
    step = c.first_step.rstrip(".")
    return c.title or (step if len(step) <= 100 else step[:100].rsplit(" ", 1)[0] + " …")


def render(states: list[State], picked: list[State], branches, uncovered, missing, head: str, today: str) -> tuple[str, str]:
    top = [f"Worked out by `spikes/owner_checks/plan.py` on {today} at `{head}`, from the ledger of past results",
           "and what changed in the code since. Most urgent first, a section at a time (each section's setup is",
           "at its heading); a check that builds on another comes after it.",
           ""]
    sections: dict[str, list[State]] = {}
    for s in picked:  # a section keeps the place of its most urgent check
        sections.setdefault(s.check.section, []).append(s)
    i = 0
    for section, items in sections.items():
        top += [f"**{section}**", ""]
        for s in items:
            i += 1
            top.append(f"{i}. {link(s.check)}: {name(s.check)}. *Why: {s.why}.*")
        top.append("")
    top += ["Then run the report (\"After the checks\", at the end) and paste what it prints."]

    groups: dict[str, list[State]] = {}
    for s in states:
        groups.setdefault(s.kind, []).append(s)
    bottom = [f"As of {today} at `{head}`. Each number links to its check.", ""]
    for kind in LABEL:
        if kind in groups:
            ids = ", ".join(link(s.check) for s in sorted(groups[kind], key=lambda s: s.check.num))
            bottom.append(f"- **{LABEL[kind]}** ({len(groups[kind])}): {ids}")
    if groups.get("failing"):
        bottom += ["", "**Waiting for a fix** (a session fixes these; they come back to the list once their code changes):", ""]
        bottom += [f"- {link(s.check)} {name(s.check)}: {s.why}." for s in groups["failing"]]
    if branches:
        bottom += ["", "**On branches not merged yet:**", ""]
        for b, new, hit in branches:
            bits = []
            if new:
                bits.append(f"adds checks {', '.join(new)}")
            if hit:
                bits.append(f"changes code behind {len(hit)} check{'s' * (len(hit) != 1)} here ({', '.join(hit[:12])}{', …' if len(hit) > 12 else ''})")
            bottom.append(f"- `{b}`: {'; '.join(bits)}.")
    free = 1 + max([s.check.num for s in states] + [int(re.match(r"\d+", i).group()) for _, new, _ in branches for i in new])
    bottom += ["", f"**Next free check number: {free}** (counted across `main` and every open branch)."]
    if uncovered:
        bottom += ["", f"**Code changed in the last {RECENT_DAYS} days that no check covers** (add a check, or add the file to an area or to `ignore` in the ledger):", ""]
        bottom += [f"- `{f}`: {n} commit{'s' * (n != 1)}" for f, n in uncovered]
    if missing:
        bottom += ["", "**Docs that name a check this file doesn't have** (renumbered or removed):", ""]
        bottom += [f"- `{p}`: check {n}" for p, n in missing]
    return "\n".join(top), "\n".join(bottom)


def replace_block(text: str, tag: str, body: str) -> str:
    start, end = f"<!-- {tag}:start -->", f"<!-- {tag}:end -->"
    if start not in text or end not in text:
        raise SystemExit(f"owner-checks.md has no {start} … {end} block")
    head, rest = text.split(start, 1)
    return f"{head}{start}\n{body}\n{end}{rest.split(end, 1)[1]}"


def main_commit_at(when: str) -> str:
    return git("rev-list", "-1", "--first-parent", f"--before={when}", "main").strip()[:7]


def report_ids(name: str, checks: dict[str, Check]) -> list[str]:
    """'77, 79-80 Swift restarted…' -> ['77', '79', '80']."""
    m = re.match(r"((?:\d+[a-z]?(?:-\d+)?)(?:,\s*\d+[a-z]?(?:-\d+)?)*)\s", name)
    return expand([p.strip() for p in m.group(1).split(",")], checks) if m else []


def parse_report(text: str, known_names: set[str], checks: dict[str, Check]) -> tuple[str, dict[str, list[str]], int]:
    """A pasted report -> (its start time, {outcome: ids}, lines skipped as no longer meaning the same check)."""
    m = re.search(r"\d+ requests since (\d{4}-\d\d-\d\d \d\d:\d\d)", text)
    if not m:
        raise SystemExit("That isn't a report.py output: no 'N requests since …' line")
    seen: dict[str, set[str]] = {}
    skipped = 0
    for outcome, rest in re.findall(r"^\s*(PASS|FAIL|NOT SEEN|LOOK)\s+(.+?)\s*$", text, re.M):
        line = re.split(r"\s{3}\(", rest, maxsplit=1)[0].strip()
        if line not in known_names:  # renamed or renumbered since: it may mean another check now
            skipped += 1
            continue
        for cid in report_ids(line, checks):
            seen.setdefault(cid, set()).add(outcome)
    out: dict[str, list[str]] = {}
    for cid, got in seen.items():
        # LOOK is printed whether or not the check was run, so alone it says nothing happened.
        verdict = ("FAIL" if "FAIL" in got else "PASS" if got == {"PASS"} else "PARTIAL" if "PASS" in got else None)
        if verdict:
            out.setdefault(verdict, []).append(cid)
    return m.group(1), out, skipped


def append_run(run: dict) -> None:
    line = yaml.safe_dump([run], default_flow_style=None, sort_keys=False, allow_unicode=True, width=10_000)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(line)


def compute(checks: dict[str, Check], led: dict, limit: int = 15):
    """Every check's state, the run list, the open branches, recent commits, main's head and now."""
    today = datetime.now()
    since = {sha: commits(f"{sha}..main") for sha in {str(r["commit"]) for r in led["runs"]}}
    recent = commits(f"--since={today - timedelta(days=RECENT_DAYS):%Y-%m-%d}", "main")
    states = assess(checks, led["runs"], since, recent, births(), today)
    return states, run_list(states, limit), branch_view(checks), recent, git("rev-parse", "--short", "main").strip(), today


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite the two generated blocks in owner-checks.md")
    ap.add_argument("--record", type=Path, help="a file holding a pasted report.py output")
    ap.add_argument("--set", nargs="+", metavar="ID=OUTCOME", help="the owner's verdicts: pass, fail, retired, blocked")
    ap.add_argument("--note", default="", help="what the owner said, for --set and --record")
    ap.add_argument("--date", help="YYYY-MM-DD HH:MM of the run, for --set (default now)")
    ap.add_argument("--commit", help="the commit Swift ran, when known (default: main at the run's time)")
    ap.add_argument("--limit", type=int, default=15, help="how many checks to put in the run list")
    args = ap.parse_args()
    checks, led = load()

    if args.record:
        sys.path.insert(0, str(Path(__file__).parent))
        import report
        names = {n for n, _, _ in report.checks([], [])}
        when, got, skipped = parse_report(args.record.read_text(encoding="utf-8"), names, checks)
        run = {"date": when, "commit": args.commit or main_commit_at(when), "source": "report", **({"note": args.note} if args.note else {}),
               "checks": got}
        append_run(run)
        print(f"Recorded the run of {when}: " + ", ".join(f"{len(v)} {k}" for k, v in got.items())
              + (f"; {skipped} line(s) skipped, renamed since" if skipped else ""))
        checks, led = load()
    if args.set:
        when = args.date or datetime.now().strftime("%Y-%m-%d %H:%M")
        got: dict[str, list[str]] = {}
        for item in args.set:
            cid, _, outcome = item.partition("=")
            outcome = outcome.upper()
            if cid not in checks or outcome not in VERDICTS:
                raise SystemExit(f"{item}: needs a check in owner-checks.md and one of {', '.join(VERDICTS)}")
            got.setdefault(outcome, []).append(cid)
        append_run({"date": when, "commit": args.commit or main_commit_at(when), "source": "owner",
                    **({"note": args.note} if args.note else {}), "checks": got})
        print(f"Recorded your verdicts of {when}: " + ", ".join(f"{k} {', '.join(v)}" for k, v in got.items()))
        checks, led = load()
    if (args.record or args.set) and not args.write:
        return

    states, picked, branches, recent, head, today = compute(checks, led, args.limit)
    top, bottom = render(states, picked, branches, gaps(led, recent), dangling(checks), head, f"{today:%Y-%m-%d}")
    print("Run these first\n\n" + top + "\n\nWhere every check stands\n\n" + bottom)
    if args.write:
        text = CHECKS.read_text(encoding="utf-8")
        text = replace_block(replace_block(text, "roadmap", top), "status", bottom)
        CHECKS.write_text(text, encoding="utf-8", newline="\n")
        print(f"\nWrote both blocks into {CHECKS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

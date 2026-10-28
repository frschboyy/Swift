"""The workflow library: packages on disk, validated, matched to requests (ADR-011 §4, §6).

A workflow is a folder with ``SKILL.md`` (the playbook, Agent Skills format) and
``swift.yaml`` (Swift's manifest). W1 reads this subset of the manifest:

| Field | Meaning |
|---|---|
| ``schema`` | ``swift.workflow/v0`` |
| ``name``, ``version``, ``title`` | The folder's name (and the skill's), a semantic version, what the owner reads |
| ``triggers`` | ``- say: ["email {person} saying {message}", ...]``; slots are declared ``inputs`` |
| ``inputs``, ``settings`` | Typed: text, choice (``of``), contact, folder, project, date; optional ``default`` |
| ``needs`` | Capabilities from ``CAPABILITIES``: the only Swift tools (and provider tools) a run may use |
| ``run`` | ``playbook: SKILL.md``; ``provider``: ``any`` or a provider id; ``demand``: ``light`` or ``standard`` (the model runs start on) |
| ``shows`` | Artifact kinds the workflow produces |

Anything else (recipes, schedules, budgets) is reported as not supported yet, and
the package is skipped. Two places are read: the built-in library next to this file
and the owner's ``%APPDATA%\\Swift\\workflows``; an owner's package with a built-in's
name replaces it. ``installed/`` (ADR-011 §6.6) is later work and not read.

Matching (ADR-011 §6.2): a trigger phrase whose slots all fill runs the workflow, and
so does an ``intent`` trigger: one of its action words and one of its subject words
anywhere in a request that isn't a question ("set up a meeting with the professor on
my calendar"). An intent marked ``questions: true`` is the opposite: it runs only on a
question ("what's on my calendar tomorrow", "when is my next meeting"), for workflows
that answer them by looking something up. In place of subject words an intent can take a new
time (``times: true``: "move Swift check to two p.m.") or the title of one of the owner's
calendar events (``titles: true``: "cancel Swift check", heard as "swift deck" too), from the
titles the caller passes to ``match``. A request that only shares words with a workflow's title and
description is offered. Running directly is safe: anything consequential still waits
for the owner on a confirm card.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger

from swift.workflows.artifacts import KINDS

BUILTIN_DIR = Path(__file__).parent / "library"
SCHEMA = "swift.workflow/v0"
INPUT_TYPES = ("text", "choice", "contact", "folder", "project", "date")
Risk = Literal["read", "none", "reversible", "external"]

# Capability -> (Swift tool it allows, or None for the provider's own tool; risk). Swift's
# table: a workflow names what it needs, Swift decides what that means (ADR-005).
CAPABILITIES: dict[str, tuple[str | None, Risk]] = {
    "email.find_contact": ("find_contact", "read"),
    "email.draft": ("draft_email", "none"),
    "email.fill_in": ("fill_in_email", "reversible"),
    "email.send": ("send_email", "external"),
    "calendar.list_events": ("list_calendar_events", "read"),
    "calendar.create_event": ("create_calendar_event", "external"),
    "calendar.update_event": ("update_calendar_event", "external"),
    "calendar.delete_event": ("delete_calendar_event", "external"),
    "swift.undo": ("undo_last_action", "external"),
    "swift.present": ("present", "none"),
    "desktop.context": ("desktop_context", "read"),
    "desktop.write": ("desktop_write", "reversible"),
    "desktop.open": ("desktop_open", "reversible"),
    "system.action": ("system_action", "reversible"),
    "web.search": (None, "read"),
    "web.fetch": (None, "read"),
}

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_WORD = re.compile(r"[a-z0-9']+")
_LEAD = r"(?:(?:hey |ok |okay )?swift[\s,]+)?(?:(?:please|can you|could you|would you)[\s,]+)*"
_GAP = r"[\s,.:;!?-]+"
# A request opening with one of these asks something; an intent trigger never runs on it
# ("what's on my calendar", "did I add the meeting").
_QUESTION = frozenset(
    "what what's whats when where which who whose why how did do does is are was were have has had am "
    "should will shall isn't aren't didn't don't doesn't".split()
)
# Words that say nothing about which workflow is meant.
_STOP = frozenset(
    "a an and the to of in on for with into from by at as is are be it its this that these those my your our "
    "me you i we they them what which who how when where why can could would should will please swift use "
    "using some any all one new about up out then there here just also get make do does did have has".split()
)


_NUMBER = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
# A new time or day after "to" / "for" ("to two p m", "for 14 00", "to friday", "until tomorrow"), in the
# words ``_WORD`` leaves ("p.m." -> "p m"). Bare numbers don't count: "change the font to 12".
_TIME = re.compile(
    rf" (?:to|for|until|till) (?:(?:next|this|the) )?(?:{_NUMBER}(?: \d{{2}}| thirty| fifteen| forty five)?"
    rf" ?(?:a m|p m|am|pm|o'?clock)|\d{{1,2}} \d{{2}}|noon|midday|midnight|tomorrow|tonight|today|morning"
    r"|afternoon|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|weekend|month"
    r"|\d{1,2}(?:st|nd|rd|th))\b"
)
# How close a name as heard must be to an event's title ("swift deck" for "Swift check" is 0.84).
TITLE_LIKENESS = 0.75
_TITLE_FILLER = frozenset("the my our a an meeting event appointment call".split())


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def likeness(heard: str, title: str) -> float:
    """How alike a name as heard is to a title, 0 to 1, by its letters ("Flift Tech" / "Swift check": 0.53)."""
    a, b = _letters(heard), _letters(title)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def names_title(words: list[str], titles: Iterable[str]) -> bool:
    """Whether some run of ``words`` sounds like one of ``titles`` ("swift deck" for "Swift check")."""
    words = [w for w in words if w not in _TITLE_FILLER]
    for title in titles:
        size = len(_WORD.findall(title.lower()))
        if not size:
            continue
        for n in {max(1, size - 1), size, size + 1}:
            for i in range(max(1, len(words) - n + 1)):
                if likeness(" ".join(words[i:i + n]), title) >= TITLE_LIKENESS:
                    return True
    return False


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class InputSpec:
    type: str
    of: tuple[str, ...] = ()
    default: str | None = None


@dataclass(frozen=True)
class Trigger:
    phrase: str
    pattern: re.Pattern[str]
    slots: tuple[str, ...]
    # Literal words: a more specific phrase is tried first.
    weight: int


def is_question(text: str) -> bool:
    """Whether a request asks something ("what's on my calendar", "did I add it?") rather than says what to do."""
    said = " ".join(_WORD.findall(text.lower()))
    lead = re.match(_LEAD, said)
    words = said[lead.end():].split() if lead else said.split()
    return text.rstrip().endswith("?") or bool(words) and words[0] in _QUESTION


_SHOW = re.compile(r"(?:show|let me see|bring up|pull up|where is|where's)\b")
# "Show me my calendar" looks up the owner's own things, which a workflow does; it isn't Swift's last result.
_SHOW_MINE = re.compile(r"(?:show|let me see|bring up|pull up)(?: me)? my\b")


def is_show(text: str) -> bool:
    """Whether a request asks to see something ("show me the Word document"): never a workflow (ADR-007 §10)."""
    said = " ".join(_WORD.findall(text.lower()))
    lead = re.match(_LEAD, said)
    said = said[lead.end():] if lead else said
    said = re.sub(r"^(?:(?:and|so|ok|okay|now|then|just)\s+)+", "", said)
    return bool(_SHOW.match(said)) and not _SHOW_MINE.match(said)


@dataclass(frozen=True)
class Intent:
    """Run when a request has one of ``actions`` and one of ``subjects`` (whole words or phrases).

    Requests that ask something never run an intent, so "did I add the meeting?" doesn't add
    one; an intent with ``questions`` runs only on those (its actions are question words).
    Instead of a subject, ``times``: a new time after the action ("move Swift check to two p.m.");
    ``titles``: the request opens with the action, then names one of ``titles`` ("cancel Swift check")."""

    actions: tuple[str, ...]
    subjects: tuple[str, ...] = ()
    questions: bool = False
    times: bool = False
    titles: bool = False

    def matches(self, text: str, titles: Iterable[str] = ()) -> bool:
        if is_question(text) != self.questions:
            return False
        said = " ".join(_WORD.findall(text.lower()))
        lead = re.match(_LEAD, said)
        said = (said[lead.end():] if lead else said).strip()
        said = " " + re.sub(r"^(?:(?:and|so|ok|okay|now|then|just|actually|also|please)\s+)+", "", said) + " "
        actions = [a for a in self.actions if f" {a} " in said]
        if not actions:
            return False
        if any(f" {s} " in said for s in self.subjects):
            return True
        if self.times and any(_TIME.search(said[said.index(f" {a} ") + len(a) + 1:]) for a in actions):
            return True
        opening = next((a for a in actions if said.startswith(f" {a} ")), None)
        if self.titles and titles and opening is not None:
            named = said[len(opening) + 1:]
            if (when := _TIME.search(named)) is not None:  # "move swift check to two p m": the name ends there
                named = named[:when.start()]
            return names_title(named.split(), titles)
        return False


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    title: str
    description: str
    playbook: str  # SKILL.md without its front matter
    path: Path
    source: Literal["built-in", "yours"]
    triggers: tuple[Trigger, ...] = ()
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    settings: dict[str, InputSpec] = field(default_factory=dict)
    needs: tuple[str, ...] = ()
    provider: str = "any"
    shows: tuple[str, ...] = ()
    intents: tuple[Intent, ...] = ()
    # The model its runs start on, unless the owner named one; None: as the request was routed.
    demand: Literal["light", "standard"] | None = None

    @property
    def tools(self) -> frozenset[str]:
        """The Swift tools a run of this workflow may call."""
        return frozenset(t for c in self.needs if (t := CAPABILITIES[c][0]) is not None)

    @property
    def example(self) -> str:
        return self.triggers[0].phrase if self.triggers else ""

    def request(self, inputs: dict[str, str], said: str, now: datetime | None = None) -> str:
        """What the provider gets: the playbook, the inputs, and the request as the owner said it."""
        now = now if now is not None and now.tzinfo is not None else (now or datetime.now()).astimezone()
        lines = [
            f"[Swift workflow: {self.title} ({self.name} {self.version})]",
            "Follow this playbook. Use only these Swift tools: "
            + (", ".join(sorted(self.tools)) or "none")
            + ". Anything else Swift will refuse.",
            "",
            self.playbook.strip(),
            "",
            "[Inputs]",
        ]
        for name, spec in self.inputs.items():
            value = inputs.get(name) or spec.default
            lines.append(f"{name} ({spec.type}): {value if value else '(not given: take it from the request)'}")
        if self.settings:
            lines += ["", "[Settings]"] + [f"{n}: {s.default}" for n, s in self.settings.items()]
        offset = f"{now:%z}"
        lines += ["", "[Now]", f"{now:%A %d %B %Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})"]
        lines += ["", "[The request, as the owner said it]", said.strip()]
        return "\n".join(lines)


@dataclass(frozen=True)
class Match:
    package: Package
    # "run": a trigger matched with every slot filled, or an intent did; "offer": only the description did.
    kind: Literal["run", "offer"]
    inputs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path.name}: {self.message}"


@dataclass
class Library:
    packages: dict[str, Package] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    def match(self, text: str, titles: Iterable[str] = ()) -> Match | None:
        """``titles``: the owner's calendar event titles Swift knows of, for ``titles`` intents."""
        said = text.strip()
        titles = tuple(titles)
        if is_show(said):
            return None  # "show me the Word document" asks to see something, never to run a workflow
        best: tuple[int, Package, dict[str, str]] | None = None
        for package in self.packages.values():
            for trigger in package.triggers:
                m = trigger.pattern.fullmatch(said)
                if m is None:
                    continue
                inputs = {k: v.strip(" ,.") for k, v in m.groupdict().items()}
                if not all(_fits(package.inputs[k], v) for k, v in inputs.items()):
                    continue
                if best is None or trigger.weight > best[0]:
                    best = (trigger.weight, package, inputs)
        if best is not None:
            return Match(best[1], "run", best[2])
        intended = [p for p in self.packages.values() if any(i.matches(said, titles) for i in p.intents)]
        if len(intended) == 1:
            return Match(intended[0], "run")  # inputs come from the request as said
        return self._offer(said)

    def _offer(self, said: str) -> Match | None:
        words = _words(said)
        scored = []
        for package in self.packages.values():
            title = _words(f"{package.title} {package.name.replace('-', ' ')}")
            shared = words & (title | _words(package.description))
            if len(shared) >= 2 and words & title:
                scored.append((len(shared), package))
        scored.sort(key=lambda s: -s[0])
        if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
            return None  # nothing, or not clear which
        return Match(scored[0][1], "offer")


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def _fits(spec: InputSpec, value: str) -> bool:
    if not value:
        return False
    return spec.type != "choice" or value.lower() in spec.of


def _trigger(phrase: str, inputs: dict[str, InputSpec]) -> Trigger:
    phrase = " ".join(phrase.split())
    parts = re.split(r"(\{[^}]*\})", phrase)
    slots = _SLOT.findall(phrase)
    if not slots and "{" in phrase:
        raise PackageError(f"trigger “{phrase}”: a slot is written {{name}}, lowercase")
    for slot in slots:
        if slot not in inputs:
            raise PackageError(f"trigger “{phrase}”: {{{slot}}} isn't one of the inputs")
    if len(set(slots)) != len(slots):
        raise PackageError(f"trigger “{phrase}”: a slot appears twice")
    regex, literal, previous_slot = _LEAD, 0, False
    for i, part in enumerate(p for p in parts if p.strip()):
        if part.startswith("{"):
            if previous_slot:
                raise PackageError(f"trigger “{phrase}”: two slots need words between them")
            regex += (_GAP if i else "") + f"(?P<{part[1:-1]}>.+?)"
            previous_slot = True
        else:
            words = _WORD.findall(part.lower())
            if not words:
                raise PackageError(f"trigger “{phrase}”: only letters, digits and apostrophes between slots")
            regex += (_GAP if i else "") + _GAP.join(re.escape(w) for w in words)
            literal += len(words)
            previous_slot = False
    if literal == 0:
        raise PackageError(f"trigger “{phrase}”: needs at least one word that isn't a slot")
    return Trigger(phrase, re.compile(regex + r"[\s.!?]*", re.IGNORECASE | re.DOTALL), tuple(slots), literal)


def _fields(raw: Any, where: str) -> dict[str, InputSpec]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PackageError(f"{where} must be a mapping of name: {{type: ...}}")
    out = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            raise PackageError(f"{where}: “{name}” isn't a valid name (lowercase, digits, underscores)")
        if not isinstance(spec, dict) or spec.get("type") not in INPUT_TYPES:
            raise PackageError(f"{where}.{name}: type must be one of {', '.join(INPUT_TYPES)}")
        if extra := set(spec) - {"type", "of", "default"}:
            raise PackageError(f"{where}.{name}: unknown key {', '.join(sorted(map(str, extra)))}")
        of = spec.get("of", [])
        if spec["type"] == "choice" and (not isinstance(of, list) or not of):
            raise PackageError(f"{where}.{name}: a choice needs `of: [...]`")
        default = spec.get("default")
        options = tuple(str(o).lower() for o in of)
        if default is not None and options and str(default).lower() not in options:
            raise PackageError(f"{where}.{name}: default {default!r} isn't one of {list(of)}")
        out[name] = InputSpec(spec["type"], options, None if default is None else str(default))
    return out


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise PackageError("SKILL.md must start with front matter (--- name, description ---)")
    end = text.find("\n---", 3)
    if end < 0:
        raise PackageError("SKILL.md: the front matter isn't closed with ---")
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError as exc:
        raise PackageError(f"SKILL.md front matter isn't valid YAML: {exc}") from None
    if not isinstance(meta, dict):
        raise PackageError("SKILL.md front matter must be a mapping")
    return meta, text[end + 4:].lstrip("-\n")


_KEYS = {"schema", "name", "version", "title", "triggers", "inputs", "settings", "needs", "run", "shows"}
_LATER = {"recipe": "W3", "schedule": "W5", "budget": "W3", "undo": "W3", "history": "W4", "watch": "watchers"}


def load_package(folder: Path, source: Literal["built-in", "yours"] = "built-in") -> Package:
    """Read and validate one package. ``PackageError`` says what is wrong, in words."""
    skill_path, manifest_path = folder / "SKILL.md", folder / "swift.yaml"
    for path in (skill_path, manifest_path):
        if not path.is_file():
            raise PackageError(f"{path.name} is missing")
    try:
        # A checkout with CRLF line ends still has the front matter where it's expected.
        skill = skill_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise PackageError(f"can't read it: {exc}") from None
    except yaml.YAMLError as exc:
        raise PackageError(f"swift.yaml isn't valid YAML: {exc}") from None
    meta, body = _front_matter(skill)

    name = meta.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64:
        raise PackageError("SKILL.md name must be lowercase letters, digits and hyphens (at most 64)")
    if name != folder.name:
        raise PackageError(f"SKILL.md name “{name}” must match the folder name")
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise PackageError("SKILL.md needs a description (at most 1024 characters)")
    if not body.strip():
        raise PackageError("SKILL.md has no instructions after the front matter")

    if not isinstance(manifest, dict):
        raise PackageError("swift.yaml must be a mapping")
    for key in manifest:
        if key in _LATER:
            raise PackageError(f"swift.yaml: `{key}` isn't supported yet ({_LATER[key]})")
        if key not in _KEYS:
            raise PackageError(f"swift.yaml: unknown key `{key}`")
    if manifest.get("schema") != SCHEMA:
        raise PackageError(f"swift.yaml: schema must be {SCHEMA}")
    if manifest.get("name") != name:
        raise PackageError("swift.yaml: name must match SKILL.md and the folder")
    version = str(manifest.get("version", ""))
    if not _VERSION.fullmatch(version):
        raise PackageError("swift.yaml: version must look like 1.0.0")
    title = manifest.get("title")
    if not isinstance(title, str) or not title.strip():
        raise PackageError("swift.yaml: title is missing")

    inputs = _fields(manifest.get("inputs"), "inputs")
    settings = _fields(manifest.get("settings"), "settings")

    triggers: list[Trigger] = []
    intents: list[Intent] = []
    raw_triggers = manifest.get("triggers") or []
    if not isinstance(raw_triggers, list):
        raise PackageError("swift.yaml: triggers must be a list")
    for entry in raw_triggers:
        if isinstance(entry, dict) and set(entry) == {"intent"}:
            intents.append(_intent(entry["intent"]))
            continue
        if not isinstance(entry, dict) or set(entry) != {"say"}:
            kinds = ", ".join(map(str, entry)) if isinstance(entry, dict) else str(entry)
            raise PackageError(f"swift.yaml: only `say` and `intent` triggers are supported yet (got {kinds})")
        phrases = [entry["say"]] if isinstance(entry["say"], str) else entry["say"]
        if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
            raise PackageError("swift.yaml: say must be a phrase or a list of phrases")
        triggers += [_trigger(p, inputs) for p in phrases]

    needs: list[str] = []
    raw_needs = manifest.get("needs") or []
    if not isinstance(raw_needs, list):
        raise PackageError("swift.yaml: needs must be a list")
    for need in raw_needs:
        # `- files.write: {within: ...}`: the scope is W2's; the name is checked now.
        capability = next(iter(need)) if isinstance(need, dict) and len(need) == 1 else need
        if capability not in CAPABILITIES:
            raise PackageError(f"swift.yaml: Swift has no capability `{capability}`")
        needs.append(capability)

    run = manifest.get("run")
    if not isinstance(run, dict) or run.get("playbook") != "SKILL.md":
        raise PackageError("swift.yaml: run needs `playbook: SKILL.md`")
    if extra := set(run) - {"playbook", "provider", "demand"}:
        key = sorted(map(str, extra))[0]
        raise PackageError(f"swift.yaml: run.{key} isn't supported yet" + (f" ({_LATER[key]})" if key in _LATER else ""))
    provider = str(run.get("provider", "any"))
    demand = run.get("demand")
    if demand not in (None, "light", "standard"):
        raise PackageError("swift.yaml: run.demand must be light or standard")

    shows = manifest.get("shows") or []
    if not isinstance(shows, list) or any(s not in KINDS for s in shows):
        raise PackageError(f"swift.yaml: shows must list artifact kinds ({', '.join(KINDS)})")

    return Package(
        name, version, title.strip(), " ".join(description.split()), body, folder, source,
        tuple(triggers), inputs, settings, tuple(needs), provider, tuple(shows), tuple(intents), demand,
    )


def _intent(raw: object) -> Intent:
    """``intent: {actions: [add, schedule, set up], subjects: [calendar, meeting], questions?: true}``;
    ``times: true`` or ``titles: true`` can stand in for ``subjects``."""
    flags = ("questions", "times", "titles")
    if (
        not isinstance(raw, dict) or "actions" not in raw or not set(raw) <= {"actions", "subjects", *flags}
        or ("subjects" not in raw and not (raw.get("times") or raw.get("titles")))
    ):
        raise PackageError("swift.yaml: intent needs `actions` and `subjects` (lists of words), "
                           "and optionally `questions: true`, `times: true` or `titles: true`")
    for flag in flags:
        if not isinstance(raw.get(flag, False), bool):
            raise PackageError(f"swift.yaml: intent {flag} must be true or false")
    lists: list[tuple[str, ...]] = []
    for key in ("actions", "subjects"):
        if key not in raw:
            lists.append(())
            continue
        words = raw[key]
        if not isinstance(words, list) or not words or not all(isinstance(w, str) and w.strip() for w in words):
            raise PackageError(f"swift.yaml: intent {key} must be a list of words")
        lists.append(tuple(" ".join(_WORD.findall(w.lower())) for w in words))
    return Intent(lists[0], lists[1], raw.get("questions", False), raw.get("times", False), raw.get("titles", False))


def load_library(owner_dir: Path | None = None, builtin_dir: Path = BUILTIN_DIR) -> Library:
    """The built-in packages, then the owner's. Invalid packages are reported and skipped."""
    library = Library()
    places: list[tuple[Path, Literal["built-in", "yours"]]] = [(builtin_dir, "built-in")]
    if owner_dir is not None:
        places.append((owner_dir, "yours"))
    for root, source in places:
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            if folder.name.startswith((".", "_")) or folder.name == "installed":
                continue
            try:
                package = load_package(folder, source)
            except PackageError as exc:
                library.problems.append(Problem(folder, str(exc)))
                logger.warning("workflow skipped", folder=str(folder), problem=str(exc))
                continue
            if package.name in library.packages:
                logger.info("your workflow replaces the built-in one", name=package.name)
            library.packages[package.name] = package
    logger.info("workflows loaded", count=len(library.packages), problems=len(library.problems))
    return library

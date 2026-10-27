"""The workflow library: package format, validation, matching (ADR-011 §4, §6.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from swift.workflows.library import BUILTIN_DIR, PackageError, load_library, load_package

SKILL = """---
name: {name}
description: Tidy the downloads folder into subfolders by type. Use when asked to tidy or sort downloads.
---

# Tidy downloads

1. Do the thing.
"""
MANIFEST = """schema: swift.workflow/v0
name: {name}
version: 1.0.0
title: Tidy my downloads
triggers:
  - say: ["tidy my {{folder}} folder"]
inputs:
  folder: {{type: choice, of: [downloads, desktop]}}
needs: [swift.present]
run:
  playbook: SKILL.md
"""


def package(root: Path, name: str, skill: str = SKILL, manifest: str = MANIFEST, **replace: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    text = manifest.format(name=name)
    for old, new in replace.items():
        text = text.replace(old.replace("_", " "), new)
    (folder / "SKILL.md").write_text(skill.format(name=name), encoding="utf-8")
    (folder / "swift.yaml").write_text(text, encoding="utf-8")
    return folder


def test_builtin_library_loads_cleanly() -> None:
    library = load_library()
    assert library.problems == []
    assert sorted(library.packages) == ["calendar-event", "email-draft", "research-into-word"]
    email = library.packages["email-draft"]
    assert email.source == "built-in" and email.version == "1.1.0"
    assert email.tools == {"find_contact", "draft_email", "fill_in_email", "send_email"}
    assert library.packages["research-into-word"].tools == {"desktop_write"}  # web.* are the provider's own
    assert library.packages["calendar-event"].shows == ("calendar_event", "table")
    assert library.packages["calendar-event"].tools == {
        "list_calendar_events", "create_calendar_event", "update_calendar_event", "delete_calendar_event",
        "find_contact", "undo_last_action",
    }


def test_the_exploration_examples_are_not_loaded() -> None:
    examples = Path(__file__).resolve().parents[2] / "docs" / "explorations" / "workflows"
    assert examples.is_dir() and BUILTIN_DIR != examples
    assert "email-someone" not in load_library().packages


def test_owner_library_adds_and_replaces(tmp_path: Path) -> None:
    package(tmp_path, "tidy-downloads")
    package(tmp_path, "email-draft", manifest=MANIFEST.replace("Tidy my downloads", "My email"))
    library = load_library(tmp_path)
    assert library.packages["tidy-downloads"].source == "yours"
    assert library.packages["email-draft"].title == "My email"
    assert library.problems == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"version: 1.0.0": "version: one"}, "version must look like 1.0.0"),
        ({"needs: [swift.present]": "needs: [files.delete]"}, "no capability `files.delete`"),
        ({'"tidy my {{folder}} folder"': '"tidy {{folder}} {{other}}"'}, "isn't one of the inputs"),
        ({"run:": "recipe: recipe.yaml\nrun:"}, "isn't supported yet (W3)"),
        ({'- say: ["tidy my {{folder}} folder"]': "- schedule: '0 18 * * 5'"}, "only `say` and `intent` triggers"),
        ({"title: Tidy my downloads": "titel: x"}, "unknown key `titel`"),
        ({"playbook: SKILL.md": "playbook: other.md"}, "playbook: SKILL.md"),
        ({"of: [downloads, desktop]": "of: []"}, "a choice needs"),
    ],
)
def test_invalid_manifests_are_reported_and_skipped(tmp_path: Path, change: dict[str, str], message: str) -> None:
    manifest = MANIFEST
    for old, new in change.items():
        assert old.format(name="x") in manifest.format(name="x") or old in manifest, old
        manifest = manifest.replace(old, new)
    package(tmp_path, "tidy-downloads", manifest=manifest)
    library = load_library(tmp_path)
    assert "tidy-downloads" not in library.packages
    assert len(library.problems) == 1 and message in library.problems[0].message, library.problems
    assert str(library.problems[0]).startswith("tidy-downloads: ")


def test_skill_checks(tmp_path: Path) -> None:
    with pytest.raises(PackageError, match="must match the folder"):
        load_package(package(tmp_path, "a-b", skill=SKILL.replace("name: {name}", "name: other")))
    with pytest.raises(PackageError, match="front matter"):
        load_package(package(tmp_path, "c-d", skill="# no front matter"))
    with pytest.raises(PackageError, match="needs a description"):
        load_package(package(tmp_path, "e-f", skill="---\nname: e-f\n---\nbody"))
    with pytest.raises(PackageError, match="lowercase"):
        load_package(package(tmp_path, "Bad_Name"))
    (tmp_path / "half").mkdir()
    (tmp_path / "half" / "SKILL.md").write_text(SKILL.format(name="half"), encoding="utf-8")
    with pytest.raises(PackageError, match="swift.yaml is missing"):
        load_package(tmp_path / "half")


def test_adjacent_slots_are_refused(tmp_path: Path) -> None:
    manifest = MANIFEST.replace('"tidy my {{folder}} folder"', '"tidy {{folder}} {{folder2}}"').replace(
        "inputs:", "inputs:\n  folder2: {{type: text}}"
    )
    with pytest.raises(PackageError, match="two slots need words between them"):
        load_package(package(tmp_path, "tidy-downloads", manifest=manifest))


def test_trigger_with_slots_runs_and_description_offers() -> None:
    library = load_library()
    run = library.match("Hey Swift, please email my lecturer saying I'll miss Thursday's lecture.")
    assert run is not None and run.kind == "run" and run.package.name == "email-draft"
    assert run.inputs == {"person": "my lecturer", "message": "I'll miss Thursday's lecture"}

    event = library.match("add lunch with Ada to my calendar tomorrow at noon")
    assert event is not None and event.inputs == {"event": "lunch with Ada", "when": "tomorrow at noon"}

    offer = library.match("find some sources on photosynthesis and put them in a Word document")
    assert offer is not None and offer.kind == "offer" and offer.package.name == "research-into-word"

    assert library.match("fix the failing test in session.py") is None
    assert library.match("what's the weather today") is None


def test_choice_slots_must_match(tmp_path: Path) -> None:
    package(tmp_path, "tidy-downloads")
    library = load_library(tmp_path, builtin_dir=tmp_path / "none")
    match = library.match("tidy my downloads folder")
    assert match is not None and match.kind == "run" and match.inputs == {"folder": "downloads"}
    assert (library.match("tidy my secret folder") or match).kind != "run"


def test_playbook_request() -> None:
    package = load_library().packages["calendar-event"]
    now = datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc)
    text = package.request({"event": "lunch with Ada"}, "add lunch with Ada to my calendar", now)
    assert text.startswith("[Swift workflow: Calendar events (calendar-event 2.1.0)]")
    assert ("Use only these Swift tools: create_calendar_event, delete_calendar_event, find_contact, "
            "list_calendar_events, undo_last_action, update_calendar_event.") in text
    assert "# Calendar events" in text and "name: calendar-event" not in text  # body, no front matter
    assert "event (text): lunch with Ada" in text and "when (date): (not given" in text
    assert "Monday 26 October 2026, 09:30 (UTC+00:00)" in text
    assert text.endswith("add lunch with Ada to my calendar")

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from test_voice import down, make, up_and_wait

from swift.runlog import InteractionLog


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_appends_one_ordered_line_per_record(tmp_path: Path) -> None:
    log = InteractionLog(tmp_path / "deep" / "interactions.jsonl", stt_model="base.en")
    log.append({"status": "done", "ts": "2026-10-22T21:00:00.000+03:00", "id": "a", "source": "voice", "transcript": "open it", "zzz": 1})
    log.append({"status": "cancelled", "ts": "t2", "id": "b", "source": "debug.run"})
    rows = read(tmp_path / "deep" / "interactions.jsonl")
    assert [r["id"] for r in rows] == ["a", "b"]
    assert list(rows[0])[:4] == ["ts", "id", "source", "transcript"]
    assert rows[0]["stt_model"] == "base.en" and "stt_model" not in rows[1]
    assert rows[0]["transcript"] == "open it"  # kept in full: this is the owner's research log
    assert rows[0]["zzz"] == 1 and "swift_version" in rows[0]


def test_write_failure_never_raises(tmp_path: Path) -> None:
    target = tmp_path / "is_a_dir"
    target.mkdir()
    InteractionLog(target).append({"status": "done"})  # logged, not raised


async def test_voice_interaction_record_has_every_field_the_brief_asks_for(tmp_path: Path) -> None:
    log = InteractionLog(tmp_path / "i.jsonl", stt_model="base.en")
    session, _out, _records, _rec, _stt = make()
    session.on_finish = log.append
    await down(session)
    await asyncio.sleep(0.01)
    await up_and_wait(session)

    (row,) = read(tmp_path / "i.jsonl")
    for field in ("ts", "transcript", "stt_ms", "executor", "run_ms", "interaction_ms", "steps", "status", "approvals"):
        assert field in row, field
    assert row["source"] == "voice" and row["status"] == "done" and row["transcript"] == "open my project"
    assert row["stt_ms"] == 420 and row["stt_model"] == "base.en" and row["approvals"] == []
    assert row["interaction_ms"] >= row["run_ms"] >= 0

"""Saved recordings that earn their keep (audit B-06): retention, flagging, the test set and its cap,
clearing, the improvement pass, and nothing leaving the machine."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import socket
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from loguru import logger

from swift.backend.__main__ import _make_recordings, _on_finish, _recordings_action
from swift.executors.improve import ImproveExecutor
from swift.ipc.protocol import decode
from swift.logging_setup import make_patcher
from swift.settings import Settings
from swift.stt import improve, recordings
from swift.stt.improve import Proposal, candidates, decide, error_spans, pauses, run_pass
from swift.stt.recordings import HOLD_S, MISSED_WAKE_S, REPEAT_S, Recordings, correction, same_request

SECRET = "transfer the money to Bob"  # stands in for what the owner said: must never reach a log


class Clock:
    def __init__(self) -> None:
        self.t = time.time()  # file times are real
        self.m = 1000.0

    def advance(self, s: float) -> None:
        self.t += s
        self.m += s


def tone(seconds: float = 1.0, f: float = 220.0) -> np.ndarray:
    t = np.arange(int(16_000 * seconds)) / 16_000
    return (np.sin(2 * np.pi * f * t) * 8000).astype(np.int16)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def rec(tmp_path: Path, clock: Clock) -> Recordings:
    return Recordings(tmp_path / "audio", tmp_path / "tests", keep_days=7, test_max=200,
                      clock=lambda: clock.t, mono=lambda: clock.m)


def finish(r: Recordings, clock: Clock, clip_id: str, text: str = SECRET, *, source: str = "voice",
           confidence: float | None = 0.9, status: str = "done", error: str | None = None,
           ms: int = 2000, audio: bool = True) -> list[str]:
    """A spoken request finished: its clip saved like the session does, then noted."""
    record: dict[str, Any] = {"id": clip_id, "source": source, "transcript": text, "status": status,
                              "interaction_ms": ms, "audio_s": 1.0}
    if confidence is not None:
        record["stt_confidence"] = confidence
    if error:
        record["error"] = error
    if audio:
        path = r.path_for(clip_id)
        assert path is not None
        recordings.save_wav(path, tone())
        record["audio_file"] = str(path)
    return r.note(record)


def index(r: Recordings) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in r.entries()}


# ---- retention ------------------------------------------------------------------------------


def test_sweep_deletes_clips_older_than_keep_days_and_keeps_newer(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "old", confidence=0.1)
    finish(rec, clock, "new", confidence=0.1)
    eight_days = clock.t - 8 * 86400
    os.utime(rec.audio_dir / "old.wav", (eight_days, eight_days))
    counts = rec.sweep()
    assert counts["deleted_old"] == 1 and counts["kept"] == 1
    assert not (rec.audio_dir / "old.wav").exists() and (rec.audio_dir / "new.wav").exists()
    assert set(index(rec)) == {"new"}  # the index follows the files


def test_sweep_deletes_clips_the_index_doesnt_know_unless_keep_all(tmp_path: Path, clock: Clock) -> None:
    audio = tmp_path / "audio"
    recordings.save_wav(audio / "from-before.wav", tone())
    Recordings(audio, tmp_path / "t", keep_all=True, clock=lambda: clock.t).sweep()
    assert (audio / "from-before.wav").exists()  # stt.save_audio: every clip kept, for keep_days
    counts = Recordings(audio, tmp_path / "t", clock=lambda: clock.t).sweep()
    assert counts["deleted_unflagged"] == 1 and not (audio / "from-before.wav").exists()


def test_keep_days_zero_saves_nothing_and_clears_what_is_there(tmp_path: Path, clock: Clock) -> None:
    audio = tmp_path / "audio"
    recordings.save_wav(audio / "a.wav", tone())
    r = Recordings(audio, tmp_path / "t", keep_days=0, clock=lambda: clock.t)
    assert not r.enabled and r.path_for("abc") is None
    assert r.note({"id": "abc", "source": "voice", "stt_confidence": 0.1, "status": "done"}) == []
    r.sweep()
    assert not list(audio.glob("*.wav"))


def test_settings_default_to_seven_days_and_save_audio_means_keep_all() -> None:
    s = Settings()
    assert s.audio.keep_days == 7 and s.audio.test_set_max == 200 and not s.audio.keep_all
    assert _make_recordings(s).keep_all is False
    legacy = Settings.model_validate({"stt": {"save_audio": True}, "audio": {"keep_days": 0}})
    r = _make_recordings(legacy)
    assert r.keep_all and not r.enabled  # 0 wins: nothing is saved
    assert str(r.test_dir).endswith("stt_testset") and "%" not in str(r.test_dir)


# ---- flagging -------------------------------------------------------------------------------


def test_flags_unsure_say_again_and_failed(rec: Recordings, clock: Clock) -> None:
    assert finish(rec, clock, "a", confidence=0.2) == ["unsure"]
    clock.advance(60)
    assert finish(rec, clock, "b", confidence=0.95, status="error", error="unclear_speech") == ["say_again"]
    clock.advance(60)
    assert finish(rec, clock, "c", confidence=0.95, status="error", error="crashed") == ["failed"]
    flags = {i: e["flags"] for i, e in index(rec).items()}
    assert flags == {"a": ["unsure"], "b": ["say_again"], "c": ["failed"]}


def test_an_unflagged_clip_goes_once_no_repeat_can_come(rec: Recordings, clock: Clock) -> None:
    assert finish(rec, clock, "fine") == []
    assert (rec.audio_dir / "fine.wav").exists()  # still a repeat could make it useful
    clock.advance(HOLD_S + 1)
    rec.tick()
    assert not (rec.audio_dir / "fine.wav").exists() and "fine" not in index(rec)


def test_keep_all_keeps_unflagged_clips(tmp_path: Path, clock: Clock) -> None:
    r = Recordings(tmp_path / "a", tmp_path / "t", keep_all=True, clock=lambda: clock.t, mono=lambda: clock.m)
    finish(r, clock, "fine")
    clock.advance(HOLD_S + 1)
    r.tick()
    assert (r.audio_dir / "fine.wav").exists()


def test_a_repeat_flags_the_clip_before_and_gives_its_words(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "first", "transfer the honey to Bob", confidence=0.3)
    clock.advance(4)
    finish(rec, clock, "again", SECRET, confidence=0.9, ms=1500)
    entry = index(rec)["first"]
    assert entry["flags"] == ["unsure", "repeated"] and entry["known"] == SECRET
    tests = rec.test_set()
    assert [t["id"] for t in tests] == ["first"] and tests[0]["known"] == SECRET
    assert (rec.test_dir / "first.wav").exists()


def test_a_repeat_heard_unsurely_flags_but_gives_no_words(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "first", "transfer the honey to Bob", confidence=0.3)
    clock.advance(3)
    finish(rec, clock, "again", SECRET, confidence=0.3)
    assert "repeated" in index(rec)["first"]["flags"] and "known" not in index(rec)["first"]
    assert rec.test_set() == []


def test_a_correction_gives_the_meant_words(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "first", "call ma", confidence=0.8)
    clock.advance(3)
    finish(rec, clock, "fix", "No, I said call Mum", confidence=0.9)
    assert index(rec)["first"]["known"] == "call Mum"
    assert correction("no, I said call Mum") == "call Mum" and correction("call Mum") is None
    assert correction("I meant Friday") == "Friday"


def test_after_say_it_again_the_next_request_is_the_words(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "unclear", "mumble", confidence=0.2, status="error", error="unclear_speech")
    clock.advance(15)  # reading the card takes longer than REPEAT_S
    finish(rec, clock, "clear", SECRET, confidence=0.9)
    assert index(rec)["unclear"]["known"] == SECRET


def test_a_different_request_later_is_not_a_repeat(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "first", "what time is it", confidence=0.3)
    clock.advance(REPEAT_S + 5)
    finish(rec, clock, "second", "what time is it", confidence=0.9)
    clock.advance(2)
    finish(rec, clock, "third", "open notepad", confidence=0.9)
    assert "repeated" not in index(rec)["first"]["flags"]
    assert "second" not in index(rec) or "repeated" not in index(rec)["second"]["flags"]
    assert same_request("transfer the honey to Bob", SECRET) and not same_request("open notepad", SECRET)


def test_missed_wake_phrase_is_saved_only_when_the_owner_addresses_swift_right_after(rec: Recordings,
                                                                                     clock: Clock) -> None:
    rec.heard_unaddressed(tone(1.5))
    clock.advance(3)
    finish(rec, clock, "w", SECRET, source="wake", ms=1000)
    assert index(rec)["w-miss"]["flags"] == ["missed_wake"] and (rec.audio_dir / "w-miss.wav").exists()
    # Room talk with nothing after it: never written to disk.
    rec.heard_unaddressed(tone(1.5))
    clock.advance(MISSED_WAKE_S + 5)
    finish(rec, clock, "w2", SECRET, source="wake", ms=1000)
    assert "w2-miss" not in index(rec)
    assert sorted(p.name for p in rec.audio_dir.glob("*-miss.wav")) == ["w-miss.wav"]


def test_typed_and_swift_own_requests_are_not_flagged(rec: Recordings, clock: Clock) -> None:
    assert finish(rec, clock, "typed", source="typed", confidence=0.1, audio=False) == []
    assert finish(rec, clock, "pass", source="improve", confidence=None, audio=False) == []
    assert index(rec) == {}


def test_the_index_holds_no_transcript(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "a", "transfer the honey to Bob", confidence=0.2)
    clock.advance(60)
    finish(rec, clock, "b", "please wire it today", confidence=0.95, status="error", error="crashed")
    raw = (rec.audio_dir / "index.json").read_text(encoding="utf-8")
    assert "honey" not in raw and "wire" not in raw
    allowed = {"id", "ts", "audio_s", "source", "flags", "confidence", "status", "error", "known"}
    assert all(set(e) <= allowed for e in index(rec).values())


# ---- the test set: cap and clearing --------------------------------------------------------


def test_the_test_set_is_capped_oldest_first(tmp_path: Path, clock: Clock) -> None:
    r = Recordings(tmp_path / "a", tmp_path / "t", test_max=3, clock=lambda: clock.t, mono=lambda: clock.m)
    for i in range(5):
        finish(r, clock, f"c{i}", f"take note number {i} honey", confidence=0.2)
        clock.advance(2)
        finish(r, clock, f"r{i}", f"take note number {i} money", confidence=0.9)
        clock.advance(60)
    assert [t["id"] for t in r.test_set()] == ["c2", "c3", "c4"]
    assert sorted(p.name for p in r.test_dir.glob("*.wav")) == ["c2.wav", "c3.wav", "c4.wav"]


def test_the_test_set_outlives_keep_days(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "first", "transfer the honey to Bob", confidence=0.3)
    clock.advance(3)
    finish(rec, clock, "again", SECRET)
    clock.advance(30 * 86400)
    old = clock.t - 20 * 86400
    for wav in rec.audio_dir.glob("*.wav"):
        os.utime(wav, (old, old))
    rec.sweep()
    assert not list(rec.audio_dir.glob("*.wav")) and [t["id"] for t in rec.test_set()] == ["first"]


def test_clear_wipes_clips_index_and_test_set(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "first", "transfer the honey to Bob", confidence=0.3)
    clock.advance(3)
    finish(rec, clock, "again", SECRET)
    (rec.test_dir / "improve.json").write_text("{}", encoding="utf-8")
    counts = rec.clear()
    assert counts == {"clips": 2, "test_set": 1}
    assert not list(rec.audio_dir.iterdir()) and not list(rec.test_dir.iterdir())
    assert rec.entries() == [] and rec.test_set() == []


async def test_the_tray_clear_item_wipes_and_says_so(rec: Recordings, clock: Clock) -> None:
    finish(rec, clock, "a", confidence=0.1)

    class FakeSession:
        notices: list[str] = []
        started: list[str] = []

        async def notice(self, run_id: str, text: str) -> None:
            self.notices.append(text)

        def start_own(self, executor: Any, words: str, source: str) -> None:
            self.started.append(source)

    session = FakeSession()
    act = _recordings_action(rec, session, object())  # type: ignore[arg-type]
    await act("clear")
    await act("improve")
    assert session.notices == ["Deleted 1 saved recording and the test set."] and session.started == ["improve"]
    assert not list(rec.audio_dir.glob("*.wav"))
    assert decode(json.dumps({"v": 1, "type": "recordings", "data": {"action": "clear"}})).type == "recordings"


def test_finish_hook_logs_flags_not_words(rec: Recordings, clock: Clock, tmp_path: Path) -> None:
    lines: list[str] = []
    logger.configure(patcher=make_patcher(False))  # swift.log's redaction, as setup_logging adds it
    sink = logger.add(lines.append, format="{message} {extra}")
    try:
        written: list[dict[str, Any]] = []

        class Log:
            def append(self, record: dict[str, Any]) -> None:
                written.append(record)

        path = rec.path_for("x")
        assert path is not None
        recordings.save_wav(path, tone())
        record = {"id": "x", "source": "voice", "transcript": SECRET, "stt_confidence": 0.1, "status": "done",
                  "audio_file": str(path), "steps": [], "approvals": []}
        _on_finish(Log(), rec)(record)  # type: ignore[arg-type]
        rec.sweep()
        rec.clear()
    finally:
        logger.remove(sink)
        logger.configure(patcher=None)
    assert written[0]["clip_flags"] == ["unsure"]
    assert lines and not any("money" in line or "Bob" in line for line in lines)


# ---- the improvement pass ------------------------------------------------------------------


def test_error_spans_and_candidates_follow_learn_fixes_rules() -> None:
    assert error_spans("open the Tauri app", "open the tori app") == [("tori", "Tauri", 2)]
    rows = [("open the Tauri app", "open the tori app"), ("build Tauri now", "build tori now"),
            ("set three timers", "set 3 timers"), ("Tauri is great", "tori is great")]
    props = candidates(rows, known=set())
    assert props == [Proposal("tori", "Tauri", 2)]  # "3"/"three" and the clip-start error dropped
    assert candidates(rows, known={("tori", "Tauri")}) == []


def make_test_set(r: Recordings, clock: Clock, pairs: list[tuple[str, str]]) -> None:
    for i, (heard, meant) in enumerate(pairs):
        finish(r, clock, f"c{i}", heard, confidence=0.2)
        clock.advance(2)
        finish(r, clock, f"r{i}", meant, confidence=0.9)
        clock.advance(60)


def test_run_pass_proposes_fixes_scores_and_feeds_end_of_speech(rec: Recordings, clock: Clock,
                                                               tmp_path: Path) -> None:
    make_test_set(rec, clock, [("open the tori app", "open the Tauri app"), ("build tori now", "build Tauri now")])
    heard = {"c0": "open the tori app", "c1": "build tori now"}
    order = iter(["c0", "c0", "c1", "c1"])  # each clip clean, then noisy

    def recognize(audio: np.ndarray) -> tuple[str, str]:
        text = heard[next(order)]
        return text, text

    fixes = tmp_path / "word_fixes.json"
    report = run_pass(recognize, rec, fixes)
    assert report.clips == 2 and report.proposals == [Proposal("tori", "Tauri", 2)]
    assert report.wer == pytest.approx(2 / 7, abs=0.001) and not report.dropped
    feed = json.loads((rec.test_dir / "endpoint_feed.json").read_text(encoding="utf-8"))["clips"]
    assert {f["id"] for f in feed} >= {"c0", "c1"}
    assert all(set(f) <= {"id", "flags", "words", "audio_s", "lead_s", "trail_s", "longest_pause_s"} for f in feed)
    state = (rec.test_dir / "improve.json").read_text(encoding="utf-8")
    assert "tori" not in state and "Tauri" not in state  # counts only

    # The next pass does worse on the same clips: reported.
    worse = lambda audio: ("open a story up", "open a story up")  # noqa: E731
    again = run_pass(worse, rec, fixes)
    assert again.compared == 2 and again.dropped and "worse than last time" in again.summary()
    assert "tori" not in again.summary()  # the card's summary: no transcript
    assert again.regressed == []  # neither sentence was exactly right before


def test_run_pass_reports_one_sentence_going_wrong_among_many(rec: Recordings, clock: Clock, tmp_path: Path) -> None:
    # W-03: one right sentence going wrong among 30 moves the word error rate by under DROP.
    said = "open the settings app for me now please"
    wrong = said.replace("settings", "sittings")
    make_test_set(rec, clock, [(wrong, said)] * 30)
    fixes = tmp_path / "word_fixes.json"
    first = run_pass(lambda audio: (said, said), rec, fixes)
    assert first.clips == 30 and first.wer == 0 and not first.dropped
    calls = iter(range(60))  # each clip clean, then noisy
    again = run_pass(lambda audio: (wrong, wrong) if next(calls) == 0 else (said, said), rec, fixes)
    assert again.wer_after - again.wer_before <= improve.DROP
    assert len(again.regressed) == 1 and again.dropped and "1 sentence" in again.summary()


def test_decide_writes_approved_fixes_and_remembers_rejected(tmp_path: Path) -> None:
    path = tmp_path / "word_fixes.json"
    decide(path, [Proposal("tori", "Tauri", 2)], approve=True)
    decide(path, [Proposal("deadlock", "git log", 1)], approve=False)
    store = json.loads(path.read_text(encoding="utf-8"))
    assert store["fixes"] == [{"heard": "tori", "meant": "Tauri", "count": 2, "enabled": True}]
    assert store["rejected"] == [["deadlock", "git log"]]


def test_pauses_measures_silence_around_and_inside_speech() -> None:
    silence = np.zeros(8000, dtype=np.int16)
    clip = np.concatenate([silence, tone(0.5), silence, tone(0.5), silence, silence])
    p = pauses(clip)
    assert p["audio_s"] == 3.0
    assert p["lead_s"] == pytest.approx(0.5, abs=0.05) and p["trail_s"] == pytest.approx(1.0, abs=0.05)
    assert p["longest_pause_s"] == pytest.approx(0.5, abs=0.05)


class FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.fixes: Any = None

    async def wait_loaded(self) -> None:
        return None

    def _transcribe_sync(self, audio: np.ndarray) -> Any:
        from swift.stt.transcriber import Transcription

        return Transcription(self.text, 1, 1.0)


async def drive(executor: ImproveExecutor, answer: bool | None) -> tuple[list[Any], Any]:
    run_id = await executor.start("Improve speech recognition")
    events = []
    async for event in executor.events(run_id):
        events.append(event)
        if event.type == "confirm" and answer is not None:
            await executor.reply(event.request_id, answer)
    return events, await executor.result(run_id)


async def test_the_word_fix_card_changes_nothing_until_approved(rec: Recordings, clock: Clock,
                                                                tmp_path: Path) -> None:
    make_test_set(rec, clock, [("open the tori app", "open the Tauri app")])
    fixes = tmp_path / "word_fixes.json"
    stt = FakeTranscriber("open the tori app")

    unanswered = ImproveExecutor(rec, stt, fixes, answer_s=0.05)  # type: ignore[arg-type]
    events, result = await drive(unanswered, None)
    assert [e.type for e in events] == ["step", "confirm"] and "tori" in events[1].detail
    assert not fixes.exists() and stt.fixes is None and "ask again" in result.summary

    approve = ImproveExecutor(rec, stt, fixes, configured_fixes={"vs code": "VS Code"})  # type: ignore[arg-type]
    _, result = await drive(approve, True)
    assert json.loads(fixes.read_text(encoding="utf-8"))["fixes"][0]["meant"] == "Tauri"
    assert stt.fixes.apply("the tori app on vs code") == "the Tauri app on VS Code"  # in use at once
    assert result.status == "done" and "in use now" in result.summary

    _, result = await drive(ImproveExecutor(rec, stt, fixes), None)  # type: ignore[arg-type]
    assert "No new word fixes" in result.summary  # kept fixes aren't proposed again


async def test_rejected_fixes_are_never_proposed_again(rec: Recordings, clock: Clock, tmp_path: Path) -> None:
    make_test_set(rec, clock, [("open the tori app", "open the Tauri app")])
    fixes = tmp_path / "word_fixes.json"
    stt = FakeTranscriber("open the tori app")
    await drive(ImproveExecutor(rec, stt, fixes), False)  # type: ignore[arg-type]
    events, _ = await drive(ImproveExecutor(rec, stt, fixes), None)  # type: ignore[arg-type]
    assert [e.type for e in events] == ["step"] and stt.fixes is None


# ---- nothing leaves the machine ------------------------------------------------------------


def test_no_network_module_is_imported() -> None:
    banned = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "websockets", "ssl", "ftplib", "smtplib"}
    for module in (recordings, improve, __import__("swift.executors.improve", fromlist=["x"])):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not names & banned, module.__name__


async def test_the_whole_loop_runs_with_the_network_cut(rec: Recordings, clock: Clock, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a recording tried to leave the machine")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket.socket, "sendto", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    make_test_set(rec, clock, [("open the tori app", "open the Tauri app")])
    rec.heard_unaddressed(tone())
    clock.advance(1)
    finish(rec, clock, "w", source="wake")
    rec.sweep()
    await drive(ImproveExecutor(rec, FakeTranscriber("open the tori app"), tmp_path / "f.json"), True)  # type: ignore[arg-type]
    rec.clear()
    await asyncio.sleep(0)
    # Everything it wrote is under its two folders and the word-fixes file.
    assert {p.parent for p in tmp_path.rglob("*") if p.is_file()} <= {rec.audio_dir, rec.test_dir, tmp_path}


# ---- the session's side ---------------------------------------------------------------------


async def test_session_saves_wake_clips_and_hands_over_unaddressed_speech(tmp_path: Path) -> None:
    from swift.ipc.protocol import Message

    from test_wake import AUDIO, finish as wait_run, make as make_wake

    session, _, records, _, _ = make_wake("Hey Swift, what time is it?", audio_dir=tmp_path)
    await session.hear_wake(AUDIO, time.monotonic())
    await wait_run(session)
    assert Path(records[0]["audio_file"]) == tmp_path / f"{records[0]['id']}.wav"  # a wake request's own clip

    heard: list[Any] = []
    session, _, records, _, _ = make_wake("I think swift is a nice language", audio_dir=tmp_path)
    session.on_unaddressed = heard.append
    await session.hear_wake(AUDIO, time.monotonic())
    assert len(heard) == 1 and records == []  # in memory only: nothing saved, nothing logged
    assert len(list(tmp_path.glob("*.wav"))) == 1

    actions: list[str] = []

    async def on_recordings(action: str) -> None:
        actions.append(action)

    session.on_recordings = on_recordings
    await session.handle(Message("recordings", {"action": "clear"}))
    assert actions == ["clear"]


def test_the_owner_checks_report_sees_recordings_from_counts_and_lines() -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("owner_report", root / "spikes" / "owner_checks" / "report.py")
    report = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(report)  # type: ignore[union-attr]
    rows = [{"clip_flags": ["unsure", "say_again"]}, {"clip_flags": ["failed"]}]
    log = [
        "10:00:00 | INFO | recordings swept | keep_days=7 deleted_old=12 deleted_unflagged=3 kept=4 test_set=0",
        "10:01:00 | INFO | recordings: added to the test set | size=1 dropped=0",
        "10:02:00 | INFO | recordings: missed wake phrase kept | before_s=2.1",
        "10:03:00 | INFO | improvement pass | clips=1 wer=0.1",
        "10:03:30 | INFO | word fixes decided | approved=True fixes=1",
        "10:04:00 | INFO | recordings cleared | clips=4 test_set=1",
    ]
    results = {name.split(" ")[0]: (ok, detail) for name, ok, detail in report.checks(rows, log)}
    for check in ("110", "111-113", "112-113", "114", "115", "116"):
        assert results[check][0], (check, results[check])
    assert results["110"][1] == "12 old, 3 unflagged deleted over 1 sweep(s)"
    assert results["111-113"][1] == "failed 1, say_again 1, unsure 1"
    empty = {name.split(" ")[0]: ok for name, ok, _ in report.checks([], [])}
    assert not any(empty[c] for c in ("110", "111-113", "112-113", "114", "115", "116"))

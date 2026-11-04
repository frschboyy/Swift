"""Backend entry point: ``python -m swift.backend``.

Tauri starts this process with the session token in ``SWIFT_SESSION_TOKEN``
and reads the ready line from stdout. Run it by hand for development with
``--token`` (see README).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import functools
import os
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

from swift import __version__
from swift.audio.chime import Chime
from swift.audio.recorder import MicRecorder
from swift.config.paths import app_paths
from swift.connectors.base import CalendarConnector, EmailConnector
from swift.connectors.fake import FakeCalendarConnector, FakeMailConnector
from swift.desktop.base import Desktop, NeverRead
from swift.executors.base import Executor
from swift.executors.claude_code import ClaudeCodeExecutor
from swift.executors.echo import EchoExecutor
from swift.executors.mock import MockExecutor
from swift.executors.quick import QuickModel
from swift.ipc.server import OverlayServer
from swift.attention import Attention
from swift.lifecycle import Lifecycle
from swift.parked import ParkedThreads
from swift.presence import PresenceMonitor, WindowsProbe
from swift.logging_setup import setup_logging
from swift.routing import Route, route
from swift.routing.classifier import BASE_EXAMPLES, ClassifierEstimate
from swift.routing.local import LocalOpener
from swift.runlog import InteractionLog
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.system.lane import SystemLane
from swift.session import Session
from swift.settings import Settings, SettingsError, expand, load_settings
from swift.signin import Service, SigninWatch, claude_status, open_claude_login
from swift.executors.improve import REQUEST as IMPROVE_REQUEST
from swift.executors.improve import ImproveExecutor
from swift.executors.signin import REQUEST as SIGNIN_REQUEST
from swift.executors.signin import SigninExecutor
from swift.stt.fixes import WordFixes
from swift.stt.recordings import Recordings
from swift.stt.transcriber import LocalTranscriber, ParakeetTranscriber, WhisperTranscriber
from swift.wake import WakeListener
from swift.workflows.library import Library, load_library
from swift.workflows.tools import KnownContact, ToolHost
from swift.workflows.toolset import ALL_TOOLS

READY_PREFIX = "SWIFT_BACKEND_READY"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="swift.backend")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml")
    parser.add_argument("--port", type=int, default=0, help="0 lets the OS choose")
    parser.add_argument("--token", default=None, help="dev only; normally SWIFT_SESSION_TOKEN")
    parser.add_argument("--console", action="store_true", help="also log to stderr")
    return parser.parse_args(argv)


def _on_finish(runlog: InteractionLog, recordings: Recordings | None = None) -> Callable[[dict[str, Any]], None]:
    def finish(record: dict[str, Any]) -> None:
        # Its clip flagged or dropped (audit B-06): the flags only, never the words.
        if recordings is not None and (flags := recordings.note(record)):
            record["clip_flags"] = flags
        # Full record to the local interaction log; a redacted one-line summary to swift.log.
        runlog.append(record)
        summary = {k: v for k, v in record.items() if k not in ("steps", "approvals", "ts", "id")}
        logger.bind(**summary, steps=len(record.get("steps", []))).info("interaction finished")

    return finish


def _make_transcriber(settings: Settings) -> LocalTranscriber:
    cfg = settings.stt
    fixes = WordFixes.load(Path(cfg.word_fixes_file), cfg.word_fixes)
    if cfg.engine == "parakeet":
        return ParakeetTranscriber(app_paths().models_dir, cpu_threads=cfg.cpu_threads, fixes=fixes)
    return WhisperTranscriber(
        cfg.model,
        app_paths().models_dir / "whisper",
        cpu_threads=cfg.cpu_threads,
        initial_prompt=cfg.initial_prompt,
        beam_size=cfg.beam_size,
        fixes=fixes,
    )


def _make_recordings(settings: Settings) -> Recordings:
    """Which recordings are kept, and for how long (audit B-06). ``stt.save_audio`` (the old debug
    switch) now means keep_all: every recording, still for audio.keep_days only."""
    cfg = settings.audio
    return Recordings(
        Path(settings.stt.audio_dir), Path(settings.stt.test_set_dir), keep_days=cfg.keep_days,
        keep_all=cfg.keep_all or settings.stt.save_audio, test_max=cfg.test_set_max, unsure_p=settings.stt.unclear_p,
    )


IMPROVE_EVERY_S = 7 * 86400


async def _keep_recordings(
    recordings: Recordings, session: Session, improve: ImproveExecutor | None, every_s: float = 60.0
) -> None:
    """Unflagged clips go once a repeat can't come; old ones once a day; the improvement pass once
    a week, while the owner is here and nothing runs (its card asks before changing anything)."""
    swept = time.monotonic()
    last_pass = _last_pass(recordings)
    while True:
        await asyncio.sleep(every_s)
        try:
            recordings.tick()
            if time.monotonic() - swept >= 86400:
                swept = time.monotonic()
                await asyncio.to_thread(recordings.sweep)
            if (improve is not None and time.time() - last_pass >= IMPROVE_EVERY_S and not session.busy
                    and not session.away and recordings.test_set()):
                last_pass = time.time()
                session.start_own(improve, IMPROVE_REQUEST, "improve")
        except Exception:  # noqa: BLE001 - keeping recordings tidy must outlive any one failure
            logger.exception("recordings upkeep failed")


def _last_pass(recordings: Recordings) -> float:
    """When the improvement pass last ran (its state file's time), 0 if never."""
    try:
        return (recordings.test_dir / "improve.json").stat().st_mtime
    except OSError:
        return 0.0


def _recordings_action(
    recordings: Recordings, session: Session, improve: ImproveExecutor | None
) -> Callable[[str], Awaitable[None]]:
    """The tray's "Clear saved recordings" and "Improve speech recognition"."""

    async def act(action: str) -> None:
        if action == "clear":
            counts = await asyncio.to_thread(recordings.clear)
            n = counts["clips"] + counts["test_set"]
            text = (f"Deleted {n} saved recording{'s' if n != 1 else ''} and the test set."
                    if n else "There were no saved recordings.")
            await session.notice("recordings-cleared", text)
        elif improve is not None:
            session.start_own(improve, IMPROVE_REQUEST, "improve")

    return act


def _watch_signins(settings: Settings, session: Session) -> SigninWatch | None:
    """Google's and Claude Code's sign-ins, checked at start-up, daily and when refused; one card
    each to sign in again (``swift.signin``). Never in debug mode: a demo never touches Google."""
    if settings.debug:
        return None
    uses_google = settings.connectors.email == "gmail" or settings.connectors.calendar == "google"
    executor = session.executor if isinstance(session.executor, ClaudeCodeExecutor) else None
    google_signin = google_check = None
    if uses_google:
        from swift.connectors import google

        google_signin, google_check = google.signin_flow, google.check
    if google_check is None and executor is None:
        return None

    def claude() -> str | None:
        return shutil.which("claude") if executor is not None else None

    async def claude_back() -> None:
        if executor is not None:  # the spare process started on the old sign-in
            await executor.release_spare()
            await executor.ensure_spare()

    signin = SigninExecutor(
        google_signin=google_signin, claude=claude, claude_check=lambda: claude_status(claude()),
        open_claude=open_claude_login, on_claude_back=claude_back,
    )

    def offer(services: set[Service]) -> None:
        if signin.want(services):
            session.start_own(signin, SIGNIN_REQUEST, "signin")

    watch = SigninWatch(
        offer, google=google_check, claude=(lambda: claude_status(claude())) if executor else None,
        busy=lambda: session.busy,
    )
    session.on_signin_refused = watch.refused
    if uses_google:
        from swift.connectors import google

        google.expired_listeners.append(lambda: watch.refused("google"))
    return watch


DEMO_LECTURER = KnownContact("Dr Ada Lovelace", "ada.lovelace@example.edu", ("lecturer", "professor"))


def _make_desktop(settings: Settings) -> Desktop | None:
    """Desktop awareness (ADR-012 D1-D2): the real Windows desktop, also in debug mode (it is local)."""
    cfg = settings.desktop
    if not cfg.enabled or sys.platform != "win32":
        return None
    from swift.desktop.windows import WindowsDesktop

    return WindowsDesktop(NeverRead.with_extra(cfg.never_read_apps, cfg.never_read_titles))


def _make_system(settings: Settings, session: Session) -> tuple[SystemLane, asyncio.Task[None]]:
    """The system lane (ADR-016 §3) and Swift's clock. Debug mode uses a stand-in device and keeps
    the schedule in memory, so the harness never changes the real volume or leaves timers behind."""
    from swift.system.control import FakeSystem, WindowsSystem
    from swift.system.scheduler import Scheduler

    scheduler = Scheduler(None if settings.debug else Path(settings.system.schedule_file))
    # The same journal as the gateway's: one place lists every change Swift made.
    journal = session.tools.gateway.journal if session.tools is not None else Journal(Path(settings.logging.journal))
    control = FakeSystem() if settings.debug else WindowsSystem()
    lane = SystemLane(control, scheduler, journal=journal)
    if isinstance(control, FakeSystem):  # the harness: its pretend Wi-Fi off is offline
        session.online = lambda: None if control.radio_state.get("wifi", True) else False
    else:
        from swift.network import online

        session.online = online
    session.system_chime = settings.system.chime
    logger.info("system lane", pending=len(scheduler.items), device="fake" if settings.debug else "windows")
    return lane, asyncio.create_task(scheduler.run(session.notify_due), name="scheduler")


def _make_speaker(settings: Settings, session: Session, loop: asyncio.AbstractEventLoop) -> None:
    """Swift's voice (ADR-016 §4). Debug mode records instead of speaking, like the fake device."""
    from swift.speech import FakeSpeaker, WindowsSpeaker

    cfg = settings.speech
    session.speech_replies = cfg.replies if cfg.enabled else "never"
    session.read_confirms = cfg.read_confirms
    if not cfg.enabled or cfg.replies == "never":
        return
    speaker = FakeSpeaker() if settings.debug else WindowsSpeaker(cfg.voice, cfg.rate, cfg.volume, loop=loop)
    speaker.on_done = session.speech_done
    session.speaker = speaker
    logger.info("speech", replies=cfg.replies, voice=cfg.voice or "default", device="fake" if settings.debug else "windows")


def _make_tools(settings: Settings, desktop: Desktop | None, opener: LocalOpener) -> ToolHost:
    """Swift's tools (ADR-010, ADR-011 W1, ADR-012). Debug mode always uses the fake connectors: a demo
    never touches Google."""
    kind = "fake" if settings.debug else settings.connectors.email
    connector: EmailConnector | None = None
    if kind == "fake":
        connector = FakeMailConnector()
    elif kind == "gmail":
        from swift.connectors.gmail import GmailConnector

        connector = GmailConnector()
    calendar_kind = "fake" if settings.debug else settings.connectors.calendar
    calendar: CalendarConnector | None = None
    if calendar_kind == "fake":
        calendar = FakeCalendarConnector()
    elif calendar_kind == "google":
        from swift.connectors.google_calendar import GoogleCalendarConnector

        calendar = GoogleCalendarConnector()
    contacts = tuple(KnownContact(c.name, c.email, tuple(c.aliases)) for c in settings.contacts)
    if kind == "fake" and not contacts:
        contacts = (DEMO_LECTURER,)
    journal = Journal(Path(settings.logging.journal))
    journal.report_unfinished()
    logger.info("workflow tools", email=kind, calendar=calendar_kind, desktop=desktop is not None, contacts=len(contacts))
    return ToolHost(connector, contacts, ActionGateway(journal), ALL_TOOLS, calendar=calendar, desktop=desktop,
                    opener=opener, owner_name=" ".join(settings.owner_name.split()))


def _make_library(settings: Settings) -> Library | None:
    cfg = settings.workflows
    return load_library(Path(cfg.dir)) if cfg.enabled else None


def _expanded(paths: list[str]) -> list[str]:
    """``%VAR%`` paths expanded; one naming an unset variable is left out (and logged)."""
    out = []
    for path in paths:
        try:
            out.append(expand(path))
        except ValueError:
            logger.warning("folder setting skipped: unset variable", setting=path)
    return out


def _make_executor(settings: Settings, mock: MockExecutor, tools: ToolHost | None = None) -> Executor:
    cfg = settings.executor
    match cfg.kind:
        case "mock":
            return mock
        case "claude_code":
            # An unset or out-of-range folder is reported on the first request, as an error card.
            cwd = cfg.working_dirs[cfg.default_dir] if cfg.default_dir < len(cfg.working_dirs) else None
            return ClaudeCodeExecutor(
                cwd=expand(cwd) if cwd else None,
                allowed_tools=cfg.allowed_tools,
                confirm_tools=cfg.confirm_tools,
                max_budget_usd=cfg.max_budget_usd,
                confirm_timeout_s=cfg.confirm_timeout_s,
                prewarm=cfg.prewarm,
                models=dict(cfg.models),
                escalation=cfg.escalation,
                confirm_strong=cfg.confirm_strong,
                turn_limits=dict(cfg.turn_limits),
                tools=tools,
                web=cfg.web,
                read_dirs=[*(expand(d) for d in cfg.working_dirs), *_expanded(cfg.read_dirs)],
                never_read=_expanded(cfg.never_read),
            )
        case _:
            return EchoExecutor()


def _make_router(settings: Settings) -> tuple[Callable[[str], Route] | None, ClassifierEstimate | None]:
    if not settings.routing:
        return None, None
    cfg = settings.demand_classifier
    if not cfg.enabled:
        return route, None
    estimate = ClassifierEstimate(
        Path(cfg.model_dir), [BASE_EXAMPLES, Path(cfg.examples_file)], threshold=cfg.threshold, quantized=cfg.quantized
    )
    return functools.partial(route, demand_fn=estimate), estimate


async def _report_wake(listener: WakeListener, session: Session, recorder: MicRecorder, every_s: float = 300.0) -> None:
    """Every 5 minutes, one content-free line on where wake listening's utterances went.

    Read top to bottom: blocks arriving -> speech in them -> utterances cut -> heard by the
    session -> transcribed -> wake / follow-up / other speech. The first number that drops to 0
    is where it stopped.
    """
    while True:
        await asyncio.sleep(every_s)
        logger.info("wake listening", device=recorder.device_name, **listener.take_stats(), **session.take_wake_stats())


async def _watch_microphone(recorder: MicRecorder, every_s: float = 2.0) -> None:
    """Keep the always-open microphone alive: reopen it when it stops delivering audio."""
    while True:
        await asyncio.sleep(every_s)
        try:
            await asyncio.to_thread(recorder.check_stream)
        except Exception:  # noqa: BLE001 - the watchdog must outlive any one failure
            logger.exception("microphone watchdog failed")


async def _serve(settings: Settings, token: str, port: int) -> None:
    server = OverlayServer(
        token,
        hello_payload={
            "version": __version__,
            "debug": settings.debug,
            "hotkeys": settings.hotkeys.model_dump(),
        },
    )
    # Both warm up in the background once the ready line is out (below).
    transcriber = _make_transcriber(settings)
    loop = asyncio.get_running_loop()
    wake = settings.wake
    # Wake listening keeps the stream open and remembers the last few seconds, so a request
    # spoken while the wake phrase was being transcribed is not lost.
    recorder = MicRecorder(
        loop, preroll_s=settings.audio.preroll_s, keep_open=wake.enabled, lookback_s=8.0 if wake.enabled else 0.0
    )

    recordings = _make_recordings(settings)
    await asyncio.to_thread(recordings.sweep)  # at start-up, and daily (_keep_recordings)
    router, classifier = _make_router(settings)
    desktop = _make_desktop(settings)
    opener = LocalOpener(settings)
    tools = _make_tools(settings, desktop, opener)
    mock = MockExecutor(tools=tools)
    # ADR-014 L2: cards wait while the owner is away; unfinished conversations are kept 24 h.
    # ADR-015: and until the overlay says it drew them.
    attention = Attention(require_seen=True)
    parked = ParkedThreads(Path(settings.logging.interactions).parent / "parked.json")
    session = Session(
        server.send,
        _make_executor(settings, mock, tools),
        tools=tools,
        confirm_timeout_s=settings.executor.confirm_timeout_s,
        debug_executor=mock if settings.debug else None,
        recorder=recorder,
        transcriber=transcriber,
        ptt_label=settings.hotkeys.push_to_talk,
        audio_dir=recordings.audio_dir if recordings.enabled else None,
        router=router,
        opener=opener,
        library=_make_library(settings),
        desktop=desktop,
        attention=attention,
        parked=parked,
        followup_s=settings.followup_context_s,
        unclear_p=settings.stt.unclear_p,
        reject_p=settings.stt.reject_p,
        noisy_db=settings.stt.noisy_db,
        wake_greetings=tuple(wake.greetings),
        wake_min_p=wake.min_p,
        wake_phrase_min_p=wake.phrase_min_p,
        wake_end_silence_s=wake.end_silence_s,
        wake_start_timeout_s=wake.start_timeout_s,
        wake_followup_s=wake.followup_s if wake.enabled else 0.0,
        wake_question_s=wake.question_s,
        followup_min_p=wake.followup_min_p,
        on_heard=Chime(settings.audio.chime),
        on_finish=_on_finish(
            InteractionLog(Path(settings.logging.interactions), stt_model=settings.stt.model_label), recordings
        ),
    )
    # The test set outlives audio.keep_days, so the pass works even with saving off.
    improve = ImproveExecutor(recordings, transcriber, Path(settings.stt.word_fixes_file), settings.stt.word_fixes)
    session.on_recordings = _recordings_action(recordings, session, improve)
    if wake.enabled:
        session.on_unaddressed = recordings.heard_unaddressed  # in memory; saved only before a wake phrase
    upkeep = asyncio.create_task(  # noqa: F841 - lives as long as the backend
        _keep_recordings(recordings, session, improve if settings.audio.improve_weekly else None)
    )
    server.set_handler(session.handle)
    session.overlay_connected = lambda: server.connected  # a due card waits for an overlay (B-03)
    wake_tasks: set[asyncio.Task[None]] = set()
    if wake.enabled:

        def heard(audio: Any, ended_at: float, short: bool = False) -> None:  # audio thread
            def start() -> None:
                task = loop.create_task(session.hear_wake(audio, ended_at, short))
                wake_tasks.add(task)
                task.add_done_callback(wake_tasks.discard)

            loop.call_soon_threadsafe(start)

        def peek(audio: Any) -> None:  # audio thread
            def start() -> None:
                task = loop.create_task(session.peek_wake(audio))
                wake_tasks.add(task)
                task.add_done_callback(wake_tasks.discard)

            loop.call_soon_threadsafe(start)

        # Very short clips ("stop", "show me" said briskly) only while a run or a reply window wants
        # them; the start of a long utterance checked for "hey Swift" only at rest.
        listener = WakeListener(heard, accept_short=session.wants_short, on_peek=peek, accept_peek=session.wants_peek,
                                end_silence=session.answer_pause_s)
        session.in_speech = lambda: listener.speaking  # an answer still being said joins what came before it
        recorder.tap = listener.feed
        recorder.on_reopen = listener.reset
        wake_report = asyncio.create_task(_report_wake(listener, session, recorder))  # noqa: F841

    bound = await server.start(port)
    print(f"{READY_PREFIX} port={bound}", flush=True)
    # After the ready line, so the overlay is usable sooner. A push-to-talk before
    # these finish just waits for them.
    recorder.prepare()
    if wake.enabled or settings.audio.preroll_s > 0:
        mic_watch = asyncio.create_task(_watch_microphone(recorder))  # noqa: F841 - lives as long as the backend
    transcriber.start_loading()
    if tools is not None:
        tools.known_titles()  # the calendar's titles, so "cancel Swift check" is known as a calendar request
    # ADR-014: here / idle / away, lock and sleep handling, re-warm on return, tray status.
    lifecycle = Lifecycle(
        session, server.send, recorder=recorder, transcriber=transcriber, executor=session.executor,
        wake_enabled=wake.enabled,
    )
    session.on_ready = lifecycle.announce
    session.on_listen = lifecycle.set_listening  # the tray's Pause listening (ADR-017)
    try:
        monitor = PresenceMonitor(WindowsProbe(), lifecycle.on_change)
    except (AttributeError, OSError) as exc:  # not Windows: no presence, everything stays on
        logger.warning("presence not available", error=str(exc))
    else:
        lifecycle.attach(monitor)
        session.on_owner = monitor.touch
        presence_tasks = (asyncio.create_task(monitor.run()), asyncio.create_task(lifecycle.run()))  # noqa: F841
    if classifier is not None:
        classifier.start_loading()
    if isinstance(session.executor, ClaudeCodeExecutor):
        session.executor.attention = attention
        session.executor.prepare()
        if settings.executor.quick_answers:
            # ADR-007 §10: the light lane, on the owner's existing Claude Code sign-in.
            session.quick = QuickModel(settings.executor.models["light"], prewarm=settings.executor.prewarm)
            session.quick.prepare()
    _make_speaker(settings, session, loop)
    if (signins := _watch_signins(settings, session)) is not None:
        signin_task = asyncio.create_task(signins.run())  # noqa: F841 - lives as long as the backend
    scheduler_task: asyncio.Task[None] | None = None
    if settings.system.enabled:
        session.system, scheduler_task = _make_system(settings, session)
        if session.tools is not None:
            session.tools.system = session.system  # the agent's system_action (ADR-016 §3)
    # restarted: started by Restart Swift (the tray or a stopped engine's card), not a fresh launch.
    logger.info("backend ready", port=bound, debug=settings.debug, wake=wake.enabled,
                restarted=os.environ.get("SWIFT_RESTARTED") == "1")

    # Exit when Tauri closes our stdin (normal quit). The Job Object covers crashes.
    stdin_closed = loop.run_in_executor(None, sys.stdin.read) if not sys.stdin.isatty() else asyncio.Future()
    try:
        await stdin_closed
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
        session.speaker.close()
        await session.close()
        if isinstance(session.executor, ClaudeCodeExecutor):
            await session.executor.close()
        if session.quick is not None:
            await session.quick.close()
        await server.stop()
        logger.info("backend stopped")


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        print(f"SWIFT_BACKEND_ERROR config {exc}", flush=True)
        return 2

    paths = dataclasses.replace(app_paths(), logs_dir=Path(settings.logging.app_log_dir))
    setup_logging(paths, settings.logging.level, console=args.console)

    token = args.token or os.environ.pop("SWIFT_SESSION_TOKEN", None)
    if not token:
        print("SWIFT_BACKEND_ERROR no session token", flush=True)
        return 2

    try:
        asyncio.run(_serve(settings, token, args.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

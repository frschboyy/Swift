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
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from swift import __version__
from swift.audio.recorder import MicRecorder
from swift.config.paths import app_paths
from swift.executors.base import Executor
from swift.executors.claude_code import ClaudeCodeExecutor
from swift.executors.echo import EchoExecutor
from swift.executors.mock import MockExecutor
from swift.ipc.server import OverlayServer
from swift.logging_setup import setup_logging
from swift.routing import Route, route
from swift.routing.classifier import BASE_EXAMPLES, ClassifierEstimate
from swift.routing.local import LocalOpener
from swift.runlog import InteractionLog
from swift.session import Session
from swift.settings import Settings, SettingsError, expand, load_settings
from swift.stt.fixes import WordFixes
from swift.stt.transcriber import LocalTranscriber, ParakeetTranscriber, WhisperTranscriber

READY_PREFIX = "SWIFT_BACKEND_READY"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="swift.backend")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml")
    parser.add_argument("--port", type=int, default=0, help="0 lets the OS choose")
    parser.add_argument("--token", default=None, help="dev only; normally SWIFT_SESSION_TOKEN")
    parser.add_argument("--console", action="store_true", help="also log to stderr")
    return parser.parse_args(argv)


def _on_finish(runlog: InteractionLog) -> Callable[[dict[str, Any]], None]:
    def finish(record: dict[str, Any]) -> None:
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


def _make_executor(settings: Settings, mock: MockExecutor) -> Executor:
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
    recorder = MicRecorder(asyncio.get_running_loop(), preroll_s=settings.audio.preroll_s)

    router, classifier = _make_router(settings)
    mock = MockExecutor()
    session = Session(
        server.send,
        _make_executor(settings, mock),
        debug_executor=mock if settings.debug else None,
        recorder=recorder,
        transcriber=transcriber,
        ptt_label=settings.hotkeys.push_to_talk,
        audio_dir=Path(settings.stt.audio_dir) if settings.stt.save_audio else None,
        router=router,
        opener=LocalOpener(settings),
        followup_s=settings.followup_context_s,
        on_finish=_on_finish(InteractionLog(Path(settings.logging.interactions), stt_model=settings.stt.model_label)),
    )
    server.set_handler(session.handle)

    bound = await server.start(port)
    print(f"{READY_PREFIX} port={bound}", flush=True)
    # After the ready line, so the overlay is usable sooner. A push-to-talk before
    # these finish just waits for them.
    recorder.prepare()
    transcriber.start_loading()
    if classifier is not None:
        classifier.start_loading()
    if isinstance(session.executor, ClaudeCodeExecutor):
        session.executor.prepare()
    logger.info("backend ready", port=bound, debug=settings.debug)

    # Exit when Tauri closes our stdin (normal quit). The Job Object covers crashes.
    loop = asyncio.get_running_loop()
    stdin_closed = loop.run_in_executor(None, sys.stdin.read) if not sys.stdin.isatty() else asyncio.Future()
    try:
        await stdin_closed
    finally:
        await session.close()
        if isinstance(session.executor, ClaudeCodeExecutor):
            await session.executor.close()
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

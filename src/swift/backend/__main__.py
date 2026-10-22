"""Backend entry point: ``python -m swift.backend``.

Tauri starts this process with the session token in ``SWIFT_SESSION_TOKEN``
and reads the ready line from stdout. Run it by hand for development with
``--token`` (see README).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from swift import __version__
from swift.config.paths import app_paths
from swift.audio.recorder import MicRecorder, warm_up
from swift.executors.base import Executor
from swift.executors.echo import EchoExecutor
from swift.executors.mock import MockExecutor
from swift.stt.transcriber import WhisperTranscriber
from swift.ipc.server import OverlayServer
from swift.logging_setup import setup_logging
from swift.session import Session
from swift.settings import Settings, SettingsError, load_settings

READY_PREFIX = "SWIFT_BACKEND_READY"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="swift.backend")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml")
    parser.add_argument("--port", type=int, default=0, help="0 lets the OS choose")
    parser.add_argument("--token", default=None, help="dev only; normally SWIFT_SESSION_TOKEN")
    parser.add_argument("--console", action="store_true", help="also log to stderr")
    return parser.parse_args(argv)


def _log_interaction(record: dict[str, Any]) -> None:
    """One summary line per interaction. The transcript is redacted to its length by the log filter."""
    summary = {k: v for k, v in record.items() if k not in ("steps", "confirmations")}
    logger.bind(**summary, steps=len(record.get("steps", []))).info("interaction finished")


def _make_executor(settings: Settings, mock: MockExecutor) -> Executor:
    match settings.executor.kind:
        case "mock":
            return mock
        case "claude_code":
            # ClaudeCodeExecutor arrives in Milestone 3.
            logger.warning("executor 'claude_code' is not available yet; using 'echo'")
            return EchoExecutor()
        case _:
            return EchoExecutor()


async def _serve(settings: Settings, token: str, port: int) -> None:
    server = OverlayServer(
        token,
        hello_payload={
            "version": __version__,
            "debug": settings.debug,
            "hotkeys": settings.hotkeys.model_dump(),
        },
    )
    # Load the speech model in the background: the overlay can connect meanwhile,
    # and a push-to-talk before it finishes simply waits for it.
    transcriber = WhisperTranscriber(
        settings.stt.model,
        app_paths().models_dir / "whisper",
        cpu_threads=settings.stt.cpu_threads,
        initial_prompt=settings.stt.initial_prompt,
    )
    transcriber.start_loading()
    # On this (event-loop) thread: streams are opened here, and PortAudio's WASAPI
    # backend fails to open a stream on a thread other than the one that initialized it.
    warm_up()

    mock = MockExecutor()
    session = Session(
        server.send,
        _make_executor(settings, mock),
        debug_executor=mock if settings.debug else None,
        recorder=MicRecorder(asyncio.get_running_loop()),
        transcriber=transcriber,
        ptt_label=settings.hotkeys.push_to_talk,
        on_finish=_log_interaction,
    )
    server.set_handler(session.handle)

    bound = await server.start(port)
    print(f"{READY_PREFIX} port={bound}", flush=True)
    logger.info("backend ready", port=bound, debug=settings.debug)

    # Exit when Tauri closes our stdin (normal quit). The Job Object covers crashes.
    loop = asyncio.get_running_loop()
    stdin_closed = loop.run_in_executor(None, sys.stdin.read) if not sys.stdin.isatty() else asyncio.Future()
    try:
        await stdin_closed
    finally:
        await session.close()
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

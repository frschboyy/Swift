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

from loguru import logger

from swift import __version__
from swift.config.paths import app_paths
from swift.executors.mock import MockExecutor
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


async def _serve(settings: Settings, token: str, port: int) -> None:
    server = OverlayServer(
        token,
        hello_payload={
            "version": __version__,
            "debug": settings.debug,
            "hotkeys": settings.hotkeys.model_dump(),
        },
    )
    mock = MockExecutor()
    # Milestone 1: the only executor is the mock. ClaudeCodeExecutor arrives in Milestone 3.
    session = Session(server.send, mock, debug_executor=mock if settings.debug else None)
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

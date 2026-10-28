"""WebSocket server for the overlay (PLAN.md §3).

- Binds 127.0.0.1 only. Port 0 lets the OS choose; the chosen port is
  announced on stdout as ``SWIFT_BACKEND_READY port=<n>`` for Tauri.
- The first frame must be ``hello`` carrying the session token, within
  ``HELLO_TIMEOUT_S``. Anything else closes the socket.
- One overlay at a time: a newly authenticated client replaces the old one
  (a reloaded webview reconnects without waiting for a timeout).
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from typing import Any

from loguru import logger
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from swift.ipc.protocol import MAX_FRAME_BYTES, Message, ProtocolError, decode, encode, outbound

HELLO_TIMEOUT_S = 5.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_REPLACED = 4409

Handler = Callable[[Message], Any]


class OverlayServer:
    def __init__(self, token: str, hello_payload: dict[str, Any] | None = None) -> None:
        if len(token) < 16:
            raise ValueError("session token is too short")
        self._token = token
        self._hello_payload = hello_payload or {}
        self._client: ServerConnection | None = None
        self._handler: Handler | None = None
        self._server: Server | None = None

    def set_handler(self, handler: Handler) -> None:
        self._handler = handler

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.sockets[0].getsockname()[1]

    async def start(self, port: int = 0) -> int:
        self._server = await serve(
            self._serve_client, "127.0.0.1", port, max_size=MAX_FRAME_BYTES, compression=None
        )
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def connected(self) -> bool:
        """An overlay is connected: what is sent now reaches the screen."""
        return self._client is not None

    async def send(self, msg: Message) -> None:
        client = self._client
        if client is None:
            return
        try:
            await client.send(encode(msg))
        except ConnectionClosed:
            pass

    async def _authenticate(self, ws: ServerConnection) -> bool:
        try:
            raw = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S)
            msg = decode(raw)
        except (TimeoutError, ProtocolError, ConnectionClosed):
            return False
        if msg.type != "hello":
            return False
        return hmac.compare_digest(msg.data["token"].encode(), self._token.encode())

    async def _serve_client(self, ws: ServerConnection) -> None:
        if not await self._authenticate(ws):
            logger.warning("overlay client rejected")
            await ws.close(CLOSE_UNAUTHORIZED, "unauthorized")
            return

        previous, self._client = self._client, ws
        if previous is not None:
            await previous.close(CLOSE_REPLACED, "replaced by a newer client")
        logger.info("overlay connected")
        await self.send(outbound("hello.ok", **self._hello_payload))

        try:
            async for raw in ws:
                try:
                    msg = decode(raw)
                except ProtocolError as exc:
                    await ws.send(encode(outbound("error", code="bad_message", message=str(exc), hint="")))
                    continue
                if msg.type == "hello":
                    continue
                if self._handler is not None:
                    await self._handler(msg)
        except ConnectionClosed:
            pass
        finally:
            if self._client is ws:
                self._client = None
                logger.info("overlay disconnected")

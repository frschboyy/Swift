from __future__ import annotations

import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from swift.ipc.protocol import Message, outbound
from swift.ipc.server import CLOSE_REPLACED, CLOSE_UNAUTHORIZED, OverlayServer

TOKEN = "s" * 43


def hello(token: str = TOKEN) -> str:
    return json.dumps({"v": 1, "type": "hello", "ts": 1, "data": {"token": token, "client": "test"}})


@pytest.fixture
async def server():
    srv = OverlayServer(TOKEN, hello_payload={"debug": True})
    received: list[Message] = []

    async def handler(msg: Message) -> None:
        received.append(msg)

    srv.set_handler(handler)
    await srv.start()
    srv.received = received  # type: ignore[attr-defined]
    yield srv
    await srv.stop()


def url(srv: OverlayServer) -> str:
    return f"ws://127.0.0.1:{srv.port}"


async def test_binds_loopback_only(server: OverlayServer) -> None:
    assert server._server is not None
    assert all(s.getsockname()[0] == "127.0.0.1" for s in server._server.sockets)


async def test_good_token_gets_hello_ok_and_messages_reach_handler(server: OverlayServer) -> None:
    async with connect(url(server)) as ws:
        await ws.send(hello())
        ok = json.loads(await ws.recv())
        assert ok["type"] == "hello.ok" and ok["data"]["debug"] is True
        await ws.send(json.dumps({"v": 1, "type": "cancel", "data": {}}))
        await server.send(outbound("state", state="idle"))
        assert json.loads(await ws.recv())["data"]["state"] == "idle"
    assert [m.type for m in server.received] == ["cancel"]  # type: ignore[attr-defined]


@pytest.mark.parametrize("first", [hello("wrong-token-0000"), json.dumps({"v": 1, "type": "cancel", "data": {}}), "junk"])
async def test_bad_first_frame_is_rejected(server: OverlayServer, first: str) -> None:
    async with connect(url(server)) as ws:
        await ws.send(first)
        with pytest.raises(ConnectionClosed) as info:
            await ws.recv()
        assert info.value.rcvd is not None and info.value.rcvd.code == CLOSE_UNAUTHORIZED
    assert server.received == []  # type: ignore[attr-defined]


async def test_bad_message_after_auth_gets_error_not_disconnect(server: OverlayServer) -> None:
    async with connect(url(server)) as ws:
        await ws.send(hello())
        await ws.recv()
        await ws.send(json.dumps({"v": 1, "type": "exec", "data": {"cmd": "calc"}}))
        err = json.loads(await ws.recv())
        assert err["type"] == "error" and err["data"]["code"] == "bad_message"
    assert server.received == []  # type: ignore[attr-defined]


async def test_newer_client_replaces_older(server: OverlayServer) -> None:
    async with connect(url(server)) as old:
        await old.send(hello())
        await old.recv()
        async with connect(url(server)) as new:
            await new.send(hello())
            await new.recv()
            with pytest.raises(ConnectionClosed) as info:
                await old.recv()
            assert info.value.rcvd is not None and info.value.rcvd.code == CLOSE_REPLACED


def test_short_token_refused() -> None:
    with pytest.raises(ValueError):
        OverlayServer("short")

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from swift.ipc.protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    Message,
    ProtocolError,
    decode,
    encode,
    outbound,
)


def frame(kind: str, **data: object) -> str:
    return json.dumps({"v": PROTOCOL_VERSION, "type": kind, "ts": 1, "data": data})


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (frame("hello", token="t" * 32, client="overlay"), "hello"),
        (frame("ptt", state="down"), "ptt"),
        (frame("ptt", state="up"), "ptt"),
        (frame("cancel"), "cancel"),
        (frame("confirm.reply", request_id="r1", decision="approve"), "confirm.reply"),
        (frame("confirm.reply", request_id="r1", decision="reject"), "confirm.reply"),
        (frame("debug.run", scenario="long"), "debug.run"),
        (frame("debug.ask", text="list the files"), "debug.ask"),
    ],
)
def test_valid_inbound(raw: str, kind: str) -> None:
    assert decode(raw).type == kind


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("not json", "invalid JSON"),
        ("[1, 2]", "JSON object"),
        (json.dumps({"v": 2, "type": "cancel", "data": {}}), "version"),
        (json.dumps({"type": "cancel", "data": {}}), "version"),
        (frame("rm -rf"), "unknown message type"),
        (frame("state", state="idle"), "unknown message type"),  # outbound-only type
        (frame("ptt"), "missing field 'state'"),
        (frame("ptt", state="sideways"), "must be one of"),
        (frame("ptt", state=1), "must be str"),
        (frame("confirm.reply", request_id="r1", decision="maybe"), "must be one of"),
        (frame("debug.run", scenario="explode"), "must be one of"),
        (json.dumps({"v": 1, "type": "cancel", "data": []}), "data must be"),
    ],
)
def test_invalid_inbound_is_rejected(raw: str, fragment: str) -> None:
    with pytest.raises(ProtocolError, match=fragment):
        decode(raw)


def test_binary_and_oversized_frames_rejected() -> None:
    with pytest.raises(ProtocolError):
        decode(b"{}")
    with pytest.raises(ProtocolError, match="too large"):
        decode(frame("hello", token="x" * MAX_FRAME_BYTES, client="o"))


def test_outbound_round_trip_shape() -> None:
    raw = encode(outbound("step", run_id="r", text="Reading README.md", kind="tool", ts=5))
    obj = json.loads(raw)
    assert obj["v"] == PROTOCOL_VERSION
    assert obj["type"] == "step"
    assert obj["data"]["text"] == "Reading README.md"
    assert isinstance(obj["ts"], int) and obj["ts"] > 0


def test_outbound_rejects_unknown_type_and_state() -> None:
    with pytest.raises(ValueError):
        outbound("ptt", state="down")
    with pytest.raises(ValueError):
        outbound("state", state="dancing")


def test_encode_keeps_unicode() -> None:
    assert "…" in encode(Message("transcript", {"text": "…"}, 1))


@given(st.text(max_size=200))
def test_decode_never_raises_anything_but_protocol_error(raw: str) -> None:
    try:
        decode(raw)
    except ProtocolError:
        pass

"""What the Capsule overlay needs from the backend (ADR-017): Swift speaking, pausing listening,
a card that runs out waiting in the stack, and Swift's question put off or cancelled."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from test_parked import QUESTION, asking, say
from test_presence import change, lifecycle
from test_speech import _speaking_session
from test_wake import AUDIO, finish

from swift.attention import Attention
from swift.ipc.protocol import Message, ProtocolError, decode

# ---- the protocol ---------------------------------------------------------------------------


def frame(kind: str, data: dict) -> str:  # type: ignore[type-arg]
    return json.dumps({"v": 1, "type": kind, "ts": 0, "data": data})


def test_the_new_inbound_messages_are_validated() -> None:
    assert decode(frame("speech.stop", {})).type == "speech.stop"
    assert decode(frame("listen", {"on": False})).data == {"on": False}
    with pytest.raises(ProtocolError):
        decode(frame("listen", {"on": "no"}))
    with pytest.raises(ProtocolError):
        decode(frame("listen", {}))


# ---- Swift speaking -------------------------------------------------------------------------


async def test_the_overlay_hears_when_swift_starts_and_stops_talking() -> None:
    session, out, _, speaker = _speaking_session()
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    await asyncio.sleep(0.01)
    assert [m.data for m in out.messages if m.type == "speech"] == [{"speaking": True}]
    speaker.finish()
    await asyncio.sleep(0.01)
    assert out.last("speech") == {"speaking": False}


async def test_stop_on_the_capsule_stops_only_the_voice() -> None:
    session, out, records, speaker = _speaking_session()
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    await session.handle(Message("speech.stop", {}))
    await asyncio.sleep(0.01)
    assert not speaker.speaking and speaker.stopped == 1
    assert out.last("speech") == {"speaking": False}
    assert out.last("result")["status"] == "done"  # the answer stays on screen


# ---- pausing listening (the tray) ------------------------------------------------------------


async def test_pause_closes_the_microphone_and_says_so_until_resumed() -> None:
    life, m, probe, clock, out = lifecycle()
    await life.set_listening(False)
    assert life.session.listening_paused and life.recorder.calls == ["pause"]
    assert out.last("presence")["paused"] is True and out.last("presence")["listening"] is False
    # Locking and unlocking while paused doesn't reopen it.
    probe.is_locked = True
    await change(life, m, clock)
    probe.is_locked = False
    await change(life, m, clock)
    assert "resume" not in life.recorder.calls and life.session.listening_paused
    await life.set_listening(True)
    assert life.recorder.calls[-1] == "resume" and not life.session.listening_paused
    assert out.last("presence")["paused"] is False and out.last("presence")["listening"] is True


async def test_listen_from_the_overlay_reaches_the_lifecycle() -> None:
    session, out, *_ = asking()
    asked: list[bool] = []

    async def on_listen(on: bool) -> None:
        asked.append(on)

    session.on_listen = on_listen
    await session.handle(Message("listen", {"on": False}))
    await session.handle(Message("listen", {"on": True}))
    assert asked == [False, True]


# ---- a countdown that runs out ---------------------------------------------------------------


async def test_on_expire_sets_the_card_aside_with_its_whole_time_back() -> None:
    attention = Attention()
    taken: list[str] = []
    attention.on_expire = lambda key: taken.append(key) or True
    future = asyncio.get_running_loop().create_future()
    waiting = asyncio.create_task(attention.wait("c1", future, 0.05))
    await asyncio.sleep(0.15)
    assert taken == ["c1"] and not waiting.done()
    assert attention.left("c1") == pytest.approx(0.05)  # frozen, and full again
    future.set_result(True)
    assert await asyncio.wait_for(waiting, 1) is True


async def test_without_a_taker_it_times_out_as_before() -> None:
    attention = Attention()
    attention.on_expire = lambda key: False
    with pytest.raises(TimeoutError):
        await attention.wait("c1", asyncio.get_running_loop().create_future(), 0.05)


# ---- Swift's question: Answer later, Cancel request -------------------------------------------


async def test_answer_later_puts_the_question_in_the_stack_now() -> None:
    session, out, records, stt, store = asking(question_s=25.0)
    await say(session, stt, QUESTION)
    thread = records[0]["thread"]
    await session.handle(Message("stack.action", {"id": f"parked:{thread}", "action": "skip"}))
    kept = store.newest()
    assert kept is not None and kept.reason == "asked" and kept.thread == thread
    assert out.last("followup") == {"open": False, "seconds": 0}
    assert any(i["id"] == f"parked:{thread}" for i in out.last("stack")["items"])


async def test_cancel_request_drops_the_question() -> None:
    session, out, records, stt, store = asking(question_s=0.1)
    await say(session, stt, QUESTION)
    await session.handle(Message("stack.action", {"id": f"parked:{records[0]['thread']}", "action": "end"}))
    await asyncio.sleep(0.2)  # past the question window: nothing is parked
    assert store.newest() is None
    assert out.last("followup") == {"open": False, "seconds": 0}


async def test_a_typed_request_says_so_on_its_transcript() -> None:
    session, out, records, stt, store = asking()
    await session.handle(Message("text", {"text": "what time is it"}))
    for _ in range(50):
        if any(m.type == "transcript" for m in out.messages):
            break
        await asyncio.sleep(0.02)
    assert out.last("transcript")["typed"] is True
    await session.cancel()

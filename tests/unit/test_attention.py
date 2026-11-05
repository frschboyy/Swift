"""How long a card waits (swift/attention.py)."""

from __future__ import annotations

import asyncio

import pytest

from swift.attention import Attention



# ---- 2026-11-05: a card set aside waits in the stack for a while, not for ever ---------------------


async def test_a_card_set_aside_while_the_owner_is_here_gives_up_after_aside_s() -> None:
    t = [0.0]
    att = Attention(hold_s=1000.0, aside_s=5.0, clock=lambda: t[0])
    fut: asyncio.Future[object] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(att.wait("c", fut, 45.0))
    await asyncio.sleep(0)
    att.put_aside("c")
    t[0] = 6.0
    att.check()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task, 1)


async def test_a_card_set_aside_while_away_keeps_the_long_hold() -> None:
    t = [0.0]
    att = Attention(hold_s=1000.0, aside_s=5.0, clock=lambda: t[0])
    fut: asyncio.Future[object] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(att.wait("c", fut, 45.0))
    await asyncio.sleep(0)
    att.put_aside("c")
    att.set_held(True)
    t[0] = 60.0
    att.check()
    await asyncio.sleep(0.05)
    assert not task.done()
    fut.set_result("ok")
    assert await asyncio.wait_for(task, 1) == "ok"

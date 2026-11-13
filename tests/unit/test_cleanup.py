"""swift.cleanup: a stop's clean-up reaches its end however often it is cancelled."""

import asyncio

import pytest

from swift.cleanup import in_turn, to_the_end


async def test_clean_up_cancelled_twice_still_finishes_and_the_cancel_still_shows() -> None:
    done: list[str] = []

    async def step(name: str) -> None:
        await asyncio.sleep(0.05)
        done.append(name)

    async def stopping() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await to_the_end(in_turn(step("agent stopped"), step("overlay told")))
            raise

    task = asyncio.ensure_future(stopping())
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.sleep(0.02)
    task.cancel()  # the second Stop, mid clean-up
    await asyncio.sleep(0.02)
    task.cancel()  # and Esc
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == ["agent stopped", "overlay told"]


async def test_a_failure_in_clean_up_is_raised_and_the_rest_isn_t_left_dangling() -> None:
    async def fails() -> None:
        raise RuntimeError("the agent wouldn't stop")

    async def never() -> None:
        raise AssertionError("ran after a failure")

    with pytest.raises(RuntimeError):
        await to_the_end(in_turn(fails(), never()))

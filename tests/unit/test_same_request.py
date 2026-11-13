"""One request or two (A7; owner check 197): tolerant of how speech is heard, never of what is asked."""

from __future__ import annotations

import pytest

from swift.same_request import same_request

ONE = [
    # Check 197: the speech model writes "tea" as the letter.
    ("Research the History of T", "research the history of tea."),
    ("Hey Swift, research the history of tea", "Research the history of tea"),
    ("Research history of wine", "Research the History of Wine."),
    ("Turn off the Wi Fi.", "turn off the wifi"),
    ("can you turn airplane mode on?", "turn on airplane mode"),
    # 14:44:20: "yes, turn off the Wi-Fi", heard with a short lead-in.
    ("He has turn off Wi Fi.", "Turn off the Wi Fi."),
]

TWO = [
    ("turn on the wifi", "turn off the wifi"),
    ("Research the history of wine", "Research the history of tea"),
    ("Research the history of tea with sources", "Research the history of tea"),
    ("turn off the wifi and bluetooth", "turn off the wifi"),
    ("don't turn off the wifi", "turn off the wifi"),
    ("turn it back on", "turn it on"),
    ("what's the capital of Peru", "what's the capital of France"),
    ("email Sam the notes", "email Ada the notes"),
    ("set a timer for five minutes", "set a timer for fifteen minutes"),
    ("", "turn off the wifi"),
]


@pytest.mark.parametrize(("new", "old"), ONE)
def test_said_again_is_one_request(new: str, old: str) -> None:
    assert same_request(new, old) and same_request(new, old, cut_off=True)


@pytest.mark.parametrize(("new", "old"), TWO)
def test_a_different_request_is_never_joined(new: str, old: str) -> None:
    assert not same_request(new, old) and not same_request(new, old, cut_off=True)


def test_a_cut_off_copy_is_one_only_where_asked_for_and_only_when_it_says_enough() -> None:
    whole = "how are you? Can you turn off the Wi-Fi?"
    cut = "How are you? Can you turn off the"
    assert same_request(cut, whole, cut_off=True)
    assert not same_request(cut, whole)  # the stack replaces an item: a cut-off copy never replaces a whole one
    assert not same_request(whole, cut, cut_off=True)  # the longer one says more: it is not the cut-off
    assert not same_request("turn off the", "turn off the bluetooth", cut_off=True)  # too little to tell
    assert not same_request("research the", "research the history of tea", cut_off=True)
    assert same_request("research the history of", "research the history of tea", cut_off=True)


async def test_the_same_research_misheard_while_it_runs_is_one_run() -> None:
    # Check 197 (2026-11-13): "the same research said in messier words got two cards doing the same work".
    from test_runs import finish_all, make, say, started, until

    session, out, records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say(session, stt, "Hey Swift, research the History of T.")
    await until(lambda: any(m.type == "run.voice" and m.data.get("text", "").startswith("Still on it")
                            for m in out.messages))
    assert len(agent.requests) == 1
    await finish_all(session, agent)


def test_asking_again_misheard_replaces_the_unfinished_one_in_the_stack(tmp_path) -> None:
    import time

    from swift.parked import Parked, ParkedThreads

    store = ParkedThreads(tmp_path / "parked.json")
    store.park(Parked(thread="a", request="research the history of tea", reason="stopped", at=time.time()))
    assert store.drop_same("Research the History of T") is True
    store.park(Parked(thread="b", request="turn off the wifi", reason="stopped", at=time.time()))
    assert store.drop_same("turn on the wifi") is False

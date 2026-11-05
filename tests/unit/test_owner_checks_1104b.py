"""Owner checks 2026-11-04 (evening): offline, "turn it back on", and which contact was meant.

- With Wi-Fi off, "Turn it back on" went to the agent and sat 45 s on "Connection hiccup, retrying";
  "What actions can I do when the Wi-Fi is off?" did the same.
- "Draft an email to Francis Chianu" asked "Which Francis: Francis, Francis Chianu or Muthoni,
  Francis (IITA)?".
"""

from __future__ import annotations

from test_routing import ask
from test_system_lane import _session

from swift.connectors.base import Contact
from swift.connectors.fake import FakeMailConnector
from swift.network import OFFLINE_ITEMS, OFFLINE_SAID
from swift.routing.rules import route
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.workflows import names
from swift.workflows.tools import ToolHost

# ---- offline ----------------------------------------------------------------------------------


async def test_turn_it_back_on_after_the_wifi_went_off_is_done_here() -> None:
    session, rec, spy, records = await _session()
    await ask("turn off the wifi", session)
    await ask("yes", session)
    assert session.system.control.radio_state["wifi"] is False  # type: ignore[union-attr]
    await ask("Turn it back on.", session)
    assert spy.calls == []
    assert rec.last("result")["summary"] == "Wi-Fi on."
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]
    assert records[-1]["action"] == "system_carry"


async def test_put_it_back_after_bluetooth_went_on() -> None:
    session, rec, spy, records = await _session()
    session.system.control.radio_state["bluetooth"] = False  # type: ignore[union-attr]
    await ask("turn on bluetooth", session)
    await ask("switch it back off", session)
    assert rec.last("ask")["question"] == "Turn off Bluetooth?"  # still asked: it's disruptive
    assert spy.calls == []


async def test_turn_it_on_with_nothing_switched_still_goes_to_the_agent() -> None:
    session, rec, spy, records = await _session()
    await ask("turn it on", session)
    assert records[-1]["route"] == "agent"


async def test_offline_an_agent_request_is_answered_here_at_once() -> None:
    session, rec, spy, records = await _session()
    session.online = lambda: False
    await ask("research the history of tea", session)
    assert spy.calls == []
    result = rec.last("result")
    assert result["summary"] == OFFLINE_SAID
    assert result["details"]["kind"] == "list" and result["details"]["items"][: len(OFFLINE_ITEMS)] == list(OFFLINE_ITEMS)
    assert (records[-1]["route"], records[-1]["action"]) == ("local", "offline")


async def test_offline_quick_commands_still_work() -> None:
    session, rec, spy, records = await _session(volume=40)
    session.online = lambda: False
    await ask("turn the volume up", session)
    assert rec.last("result")["summary"] == "Volume 50."


async def test_online_or_unknown_the_agent_takes_it() -> None:
    for state in (True, None):
        session, rec, spy, records = await _session()
        session.online = lambda s=state: s  # type: ignore[misc]
        await ask("research the history of tea", session)
        assert records[-1]["route"] == "agent"


def test_what_works_offline_is_answered_here() -> None:
    for said in (
        "What commands will be available if the Wi Fi is turned off?",
        "What actions can I do when the Wi Fi is off?",
        "What can you do offline?",
        "What can I still do without Wi-Fi?",
        "What works without the internet?",
    ):
        r = route(said)
        assert (r.route, r.action) == ("local", "offline_help"), said
    assert route("What's the weather when the wifi is off").route == "agent"
    assert route("What can you do?").action == "help"


async def test_what_works_offline_lists_it() -> None:
    session, rec, spy, records = await _session()
    await ask("What actions can I do when the Wi Fi is off?", session)
    assert spy.calls == []
    assert len(rec.last("result")["details"]["items"]) == len(OFFLINE_ITEMS) + 1


# ---- which contact ----------------------------------------------------------------------------

CHIANU = Contact("Francis Chianu", "francis.chianu@example.com", "gmail")
MUTHONI = Contact("Muthoni, Francis (IITA)", "f.muthoni@iita.example", "gmail")
ME = Contact("Francis", "francis@example.org", "gmail_emailed")


def _host(said: str) -> ToolHost:
    host = ToolHost(FakeMailConnector(contacts=(ME, CHIANU, MUTHONI)), (), ActionGateway(Journal(None)))
    scope = host.open(lambda *a, **k: _none(), lambda *a, **k: _none())  # type: ignore[arg-type,return-value]
    scope.said = said
    return host


async def _none() -> None:
    return None


async def test_the_whole_name_keeps_only_that_contact() -> None:
    found = await _host("Draft an email to Francis Chianu about lunch").call("find_contact", {"query": "Francis Chianu"})
    assert [c["email"] for c in found.data["candidates"]] == [CHIANU.email]


async def test_a_first_name_search_is_narrowed_by_the_owners_words() -> None:
    said = "Draft an email to Francis about lunch Francis Chianu."
    found = await _host(said).call("find_contact", {"query": "Francis"})
    assert [c["email"] for c in found.data["candidates"]] == [CHIANU.email]


async def test_a_surname_heard_a_little_wrong_still_finds_the_contact() -> None:
    for heard in ("Francis Cianu", "Francis Chanu", "Francis Chi Anu"):
        found = await _host(f"Draft an email to {heard} about lunch").call("find_contact", {"query": heard})
        assert [c["email"] for c in found.data["candidates"]] == [CHIANU.email], heard
        assert "closest" in found.text or "Found" in found.text


async def test_only_the_first_name_said_still_offers_every_francis() -> None:
    found = await _host("Email Francis about lunch").call("find_contact", {"query": "Francis"})
    assert len(found.data["candidates"]) == 3


def test_close_names() -> None:
    assert names.close("cianu", "chianu") and names.close("chanu", "chianu")
    assert not names.close("muthoni", "chianu") and not names.close("lunch", "chianu")


def test_a_name_heard_as_two_words_is_one() -> None:
    assert names.by_query("Francis Chi Anu", [CHIANU, MUTHONI, ME], exact=False) == [CHIANU]


# ---- 2026-11-05: "Sam" found only Alex Samia, and the email went to him ---------------------------

SAMIA = Contact("Alex Samia", "alex.samia@example.com", "gmail")
SAM_LEE = Contact("Sam Lee", "sam.lee@example.com", "gmail")


def _asking(contacts: tuple[Contact, ...], answer: str | None) -> tuple[ToolHost, list[str]]:
    from swift.dialogue import Answer

    asked: list[str] = []

    async def ask(question: str, kind: str, options: tuple[str, ...]) -> Answer | None:
        asked.append(question)
        return None if answer is None else Answer(answer)  # type: ignore[arg-type]

    host = ToolHost(FakeMailConnector(contacts=contacts), (), ActionGateway(Journal(None)))
    scope = host.open(lambda *a, **k: _none(), lambda *a, **k: _none(), ask=ask)  # type: ignore[arg-type,return-value]
    scope.said = "Draft an email to Sam about lunch"
    return host, asked


async def test_a_name_that_only_starts_a_contacts_name_is_asked_about() -> None:
    host, asked = _asking((SAMIA,), "no")
    found = await host.call("find_contact", {"query": "Sam"})
    assert asked == ["I couldn't find Sam. Did you mean Alex Samia?"]
    assert not found.ok and "Don't email" in found.text
    # The rejected guess isn't a recipient: it can't be drafted to afterwards.
    draft = await host.call("draft_email", {"to": [SAMIA.email], "subject": "Lunch", "message": "Lunch at one?"})
    assert not draft.ok


async def test_no_answer_about_the_close_contact_leaves_it_unusable() -> None:
    host, _ = _asking((SAMIA,), None)
    found = await host.call("find_contact", {"query": "Sam"})
    assert not found.ok
    assert not (await host.call("draft_email", {"to": [SAMIA.email], "subject": "Lunch", "message": "Hi"})).ok


async def test_a_title_is_not_part_of_the_name() -> None:
    lovelace = Contact("Ada Lovelace", "ada@example.com", "gmail")
    host, asked = _asking((lovelace,), None)
    found = await host.call("find_contact", {"query": "Dr Lovelace"})
    assert found.ok and asked == []


async def test_yes_to_the_close_contact_uses_it() -> None:
    host, _ = _asking((SAMIA,), "yes")
    found = await host.call("find_contact", {"query": "Sam"})
    assert found.ok and [c["email"] for c in found.data["candidates"]] == [SAMIA.email]


async def test_a_contact_named_sam_is_preferred_to_one_whose_name_starts_with_it() -> None:
    host, asked = _asking((SAMIA, SAM_LEE), None)
    found = await host.call("find_contact", {"query": "Sam"})
    assert [c["email"] for c in found.data["candidates"]] == [SAM_LEE.email] and asked == []

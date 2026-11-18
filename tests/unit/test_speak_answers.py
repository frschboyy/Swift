"""A8: "Speak answers" from the tray (frames.py ``speak``)."""

from swift import frames


async def test_a8_speak_answers_from_the_tray_and_default_puts_config_back() -> None:
    """A8: the tray's "Speak answers" overrides config.yaml's speech.replies; "default" restores it; no voice, no change."""
    from types import SimpleNamespace

    session = SimpleNamespace(speech_config="auto", speech_replies="auto")
    await frames.HANDLERS["speak"](session, {"replies": "never"})
    assert session.speech_replies == "never"
    await frames.HANDLERS["speak"](session, {"replies": "default"})
    assert session.speech_replies == "auto"
    off = SimpleNamespace(speech_config=None, speech_replies="never")
    await frames.HANDLERS["speak"](off, {"replies": "always"})
    assert off.speech_replies == "never"

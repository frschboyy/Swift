"""A6: captions follow the PC (muted, or Windows Live captions running) until the owner says "captions on/off"."""

from __future__ import annotations

from pathlib import Path

from swift import captions
from swift.memory import Store
from swift.system.control import SystemUnavailable


class Control:
    def __init__(self, muted: bool | None) -> None:
        self.muted = muted

    async def get_mute(self) -> bool:
        if self.muted is None:
            raise SystemUnavailable("I can't read the mute state here.")
        return self.muted


async def test_off_by_default_on_when_muted_or_live_captions_run(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await captions.refresh(Control(False), live_captions=lambda: False)
    assert not captions.is_on(store)
    await captions.refresh(Control(True), live_captions=lambda: False)
    assert captions.is_on(store) and captions.spoken(store, "Hi.") == {"text": "Hi."}
    await captions.refresh(Control(False), live_captions=lambda: True)
    assert captions.is_on(store)
    await captions.refresh(Control(None), live_captions=lambda: False)  # can't read it: as if not muted
    assert not captions.is_on(store)


async def test_the_owners_words_win_over_the_pc(tmp_path: Path) -> None:
    store = Store(tmp_path)
    await captions.refresh(Control(True), live_captions=lambda: False)
    captions.answer(store, "captions_off", "r1")
    assert not captions.is_on(store) and captions.setting(store) == "off"  # muted, but the owner said off
    captions.answer(store, "captions_on", "r2")
    await captions.refresh(Control(False), live_captions=lambda: False)
    assert captions.is_on(store)  # sound back, but the owner said on
    await captions.refresh(Control(False), live_captions=lambda: False)

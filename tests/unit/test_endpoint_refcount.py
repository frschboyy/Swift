"""The speakers' volume interface is handed to ``use`` with a reference of its own (2026-11-18 engine crashes).

``ctypes.cast`` made a second owner that Released without AddRef: every ``get_mute`` (once a minute, captions)
freed the device's object once too often, and a later COM call on the freed object killed the engine with an
access violation at _ctypes.pyd+0x7972. Reads the real device (a read, nothing changes); skipped elsewhere.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Core Audio is Windows only")


def test_interface_given_to_use_holds_its_own_reference():
    from swift.system.control import SystemUnavailable, _with_endpoint

    def refs(v) -> int:
        v.AddRef()
        return v.Release()

    try:
        count = _with_endpoint("volume", refs)
    except SystemUnavailable:
        pytest.skip("no output device")
    assert count >= 2  # Activate's pointer and ours; a cast left 1, and dropping it freed the object

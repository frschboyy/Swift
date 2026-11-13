"""B4 spike: Windows Shell thumbnails (IShellItemImageFactory) for document previews, through comtypes.

Usage: python thumb_spike.py OUT_DIR [--save] FILE...
Prints per file: kind, whether a real thumbnail came back (THUMBNAILONLY, no icon fallback), size, ms.
--save writes BMPs to OUT_DIR (only for files this spike made itself).
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

import comtypes
from comtypes import GUID, COMMETHOD, HRESULT, IUnknown

class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

class IShellItemImageFactory(IUnknown):
    _iid_ = GUID("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")
    _methods_ = [COMMETHOD([], HRESULT, "GetImage", (["in"], SIZE, "size"), (["in"], ctypes.c_int, "flags"),
                           (["out"], ctypes.POINTER(wintypes.HBITMAP), "phbm"))]

SIIGBF_BIGGERSIZEOK, SIIGBF_THUMBNAILONLY = 0x1, 0x8
shell32, gdi32 = ctypes.windll.shell32, ctypes.windll.gdi32
shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]

class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort), ("bmBitsPixel", ctypes.c_ushort),
                ("bmBits", ctypes.c_void_p)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def thumbnail(path: str, px: int = 256):
    item = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(os.path.abspath(path), None, ctypes.byref(IShellItemImageFactory._iid_), ctypes.byref(item))
    if hr != 0:
        raise OSError(f"SHCreateItemFromParsingName 0x{hr & 0xffffffff:08x}")
    factory = ctypes.cast(item, ctypes.POINTER(IShellItemImageFactory))
    return factory.GetImage(SIZE(px, px), SIIGBF_THUMBNAILONLY | SIIGBF_BIGGERSIZEOK)


def save_bmp(hbm, out: str) -> tuple[int, int]:
    bm = BITMAP()
    gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth, bm.bmHeight
    hdr = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    dc = ctypes.windll.user32.GetDC(None)
    gdi32.GetDIBits(dc, hbm, 0, h, buf, ctypes.byref(hdr), 0)
    ctypes.windll.user32.ReleaseDC(None, dc)
    hdr.biHeight = h  # bottom-up for the file
    rows = [buf.raw[r * w * 4:(r + 1) * w * 4] for r in range(h)][::-1]
    data = b"".join(rows)
    with open(out, "wb") as f:
        f.write(b"BM" + (54 + len(data)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little"))
        f.write(bytes(hdr) + data)
    return w, h


def main() -> None:
    comtypes.CoInitialize()
    out_dir, args = sys.argv[1], sys.argv[2:]
    save = "--save" in args
    files = [a for a in args if a != "--save"]
    for i, path in enumerate(files):
        kind = os.path.splitext(path)[1].lower()
        t0 = time.perf_counter()
        try:
            hbm = thumbnail(path)
            ms = (time.perf_counter() - t0) * 1000
            if save:
                w, h = save_bmp(hbm, os.path.join(out_dir, f"thumb{i}{kind}.bmp"))
            else:
                bm = BITMAP(); gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm)); w, h = bm.bmWidth, bm.bmHeight
            gdi32.DeleteObject(hbm)
            print(f"{kind}\tthumbnail\t{w}x{h}\t{ms:.0f} ms" + (f"\t{os.path.basename(path)}" if save else ""))
        except Exception as e:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000
            print(f"{kind}\tno thumbnail\t{type(e).__name__}: {str(e)[:70]}\t{ms:.0f} ms")


if __name__ == "__main__":
    main()

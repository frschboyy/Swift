"""Voice listening test: the same Swift lines in the Windows voices, Piper and Kokoro, timed on this PC.

Usage (from the repo root):

    uv run --group spikes --with kokoro-onnx==0.6.1 python spikes/tts/voice_test.py --download

``--download`` fetches what is missing, once, into %LOCALAPPDATA%\\Swift\\models\\kokoro:
``kokoro-v1.0.int8.onnx`` (about 88 MB) and ``voices-v1.0.bin``, from the kokoro-onnx GitHub
release ``model-files-v1.0``. Without it, a missing model is skipped and says so. ``--fp32`` also
tries the full model (``kokoro-v1.0.onnx``, about 310 MB), which may sound slightly better and is slower.
Piper uses the voice ``piper_bench.py`` already put in the model store; nothing is downloaded for it.

It writes ``spikes/tts/results/voices-<stamp>/``: one WAV per line and voice, ``index.html``
to listen side by side (with a "hide names" switch for a blind listen), and the timings
in ``spikes/tts/results/voices-<stamp>.json``.

What it measures, warm, per line (``--reps`` times, median kept):
  - **first audio:** time until the first sentence's audio is ready. Swift would start playing
    then, so this is the delay you would hear. ADR-016 §4's budget is 700 ms.
  - **total** and **real-time factor** (synthesis time / audio length; under 1 keeps up).
Windows SAPI renders to a file in one go, so its first audio is its total.

Spike only: never imported by src/swift, and kokoro-onnx is not added to the project
(``--with`` installs it for this run only). Licences to settle before any real use: the
Kokoro model is Apache-2.0 and kokoro-onnx MIT; its phonemizer and espeak-ng are GPL-3.0.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import sys
import tempfile
import time
import urllib.request
import wave
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _util import SPIKES_DIR, models_dir, private_mb, write_result  # noqa: E402

# What Swift actually says: short replies in their spoken form (speech.spoken), a question,
# a confirm card read aloud (speech.card_speech), a failure, and one at the 220-character limit.
LINES: dict[str, str] = {
    "timer": "Timer set for ten minutes.",
    "question": "For how long?",
    "calendar": "You're free on Tuesday from two until four. Should I put the review in at two?",
    "card": "Send this email to Ada? Subject: Running late today. Say “Swift, yes” to go ahead, or “no”.",
    "wifi": "Turn off Wi-Fi?",
    "failure": "I couldn't reach your calendar just now. I'll try again in a minute.",
    "answer": (
        "The report is due on Friday the fourteenth. Three things are still open: the figures in "
        "chapter four, the ethics form, and a reply from your supervisor about the draft."
    ),
}

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_INT8 = "kokoro-v1.0.int8.onnx"
KOKORO_FP32 = "kokoro-v1.0.onnx"
KOKORO_VOICES = "voices-v1.0.bin"
# Kokoro's better-rated English voices (a = American, b = British; f/m = female/male).
KOKORO_PICKS = ["af_heart", "af_bella", "af_nicole", "am_michael", "am_fenrir", "bf_emma", "bm_george"]

PIPER_VOICE = "en_US-lessac-medium"
WINDOWS_PICKS = ["Zira", "Mark"]  # the OneCore voices Swift can use today (speech.voice)

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])")


# --- downloads --------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, target: Path) -> None:
    """To <target>.part, renamed only when complete, so a cut-off file is never used."""
    part = target.with_name(target.name + ".part")
    print(f"downloading {target.name} ...", flush=True)
    try:
        urllib.request.urlretrieve(url, part)
    except OSError:
        part.unlink(missing_ok=True)
        raise
    part.replace(target)
    print(f"  {target.stat().st_size / 2**20:.0f} MB", flush=True)


def kokoro_files(model: str, allow_download: bool) -> tuple[Path, Path] | None:
    d = models_dir() / "kokoro"
    d.mkdir(parents=True, exist_ok=True)
    paths = (d / model, d / KOKORO_VOICES)
    for path in paths:
        if not path.exists():
            if not allow_download:
                print(f"kokoro: {path.name} missing; run with --download to fetch it")
                return None
            download(f"{KOKORO_RELEASE}/{path.name}", path)
    return paths


# --- engines: each returns (first_audio_s, total_s, float32 audio, sample_rate) ----------------

Synth = Callable[[str], tuple[float, float, np.ndarray, int]]


def windows_engine(name: str) -> tuple[str, Synth] | None:
    import pythoncom
    import win32com.client

    from swift.speech import _choose

    pythoncom.CoInitialize()
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    _choose(voice, name)
    found = voice.Voice.GetDescription()
    if name.lower() not in found.lower():
        print(f"windows: {name} not on this PC")
        return None

    def synth(text: str) -> tuple[float, float, np.ndarray, int]:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "out.wav")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
            fmt.Type = 34  # SAFT24kHz16BitMono
            stream.Format = fmt
            start = time.perf_counter()
            stream.Open(path, 3)  # SSFMCreateForWrite
            voice.AudioOutputStream = stream
            voice.Speak(text, 0)  # synchronous
            stream.Close()
            total = time.perf_counter() - start
            audio, rate = read_wav(Path(path))
        return total, total, audio, rate

    return f"Windows {found.split(' - ')[0].removeprefix('Microsoft ')}", synth


def piper_engine() -> tuple[str, Synth] | None:
    path = models_dir() / "piper" / PIPER_VOICE / f"{PIPER_VOICE}.onnx"
    if not path.exists():
        print("piper: no voice in the model store (piper_bench.py fetches it); skipped")
        return None
    from piper import PiperVoice

    voice = PiperVoice.load(str(path))

    def synth(text: str) -> tuple[float, float, np.ndarray, int]:
        chunks, first, rate = [], None, 22050
        start = time.perf_counter()
        for chunk in voice.synthesize(text):  # one chunk per sentence
            first = first if first is not None else time.perf_counter() - start
            rate = chunk.sample_rate
            chunks.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16).astype(np.float32) / 32768)
        total = time.perf_counter() - start
        return first or total, total, np.concatenate(chunks), rate

    synth("Warm up.")
    return "Piper lessac", synth


def kokoro_engine(model: Path, voices: Path, label: str) -> tuple[object, Callable[[str], tuple[str, Synth]]]:
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(str(model), str(voices))

    def for_voice(name: str) -> tuple[str, Synth]:
        def synth(text: str) -> tuple[float, float, np.ndarray, int]:
            # Sentence by sentence, as Swift would play it: the first sentence is what you wait for.
            chunks, first, rate = [], None, 24000
            start = time.perf_counter()
            for sentence in _SENTENCE.split(text):
                audio, rate = kokoro.create(sentence, voice=name, speed=1.0, lang=lang_of(name))
                first = first if first is not None else time.perf_counter() - start
                chunks.append(audio.astype(np.float32))
                chunks.append(np.zeros(int(rate * 0.25), dtype=np.float32))
            total = time.perf_counter() - start
            return first or total, total, np.concatenate(chunks[:-1]), rate

        return f"Kokoro {name}{label}", synth

    for_voice(KOKORO_PICKS[0])[1]("Warm up.")  # first call allocates the ONNX session
    return kokoro, for_voice


def lang_of(voice: str) -> str:
    return "en-gb" if voice.startswith("b") else "en-us"


# --- audio files ------------------------------------------------------------------------------


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768, rate


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# --- the run ----------------------------------------------------------------------------------


def measure(label: str, synth: Synth, reps: int, out: Path) -> dict:
    rows = {}
    for key, text in LINES.items():
        firsts, totals = [], []
        for _ in range(reps):
            first, total, audio, rate = synth(text)
            firsts.append(first)
            totals.append(total)
        audio_s = len(audio) / rate
        name = f"{key}--{slug(label)}.wav"
        write_wav(out / name, audio, rate)
        rows[key] = {
            "file": name,
            "first_audio_s": round(statistics.median(firsts), 3),
            "total_s": round(statistics.median(totals), 3),
            "audio_s": round(audio_s, 2),
            "rtf": round(statistics.median(totals) / audio_s, 3) if audio_s else None,
        }
    worst = max(r["first_audio_s"] for r in rows.values())
    print(f"{label:28} first audio worst {worst * 1000:5.0f} ms", flush=True)
    return rows


def page(results: dict[str, dict], stamp: str) -> str:
    voices = list(results)
    head = "".join(f'<th><span class="name">{html.escape(v)}</span><span class="code">{chr(65 + i)}</span></th>'
                   for i, v in enumerate(voices))
    body = []
    for key, text in LINES.items():
        cells = []
        for v in voices:
            r = results[v]["lines"][key]
            ms = r["first_audio_s"] * 1000
            cells.append(
                f'<td><audio controls preload="none" src="{html.escape(r["file"])}"></audio>'
                f'<div class="t {"slow" if ms > 700 else ""}">{ms:.0f} ms to start · RTF {r["rtf"]}</div></td>'
            )
        body.append(f'<tr><th class="line">{html.escape(text)}</th>{"".join(cells)}</tr>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Swift voices {stamp}</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ margin: 24px; }} table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #8884; padding: 8px; vertical-align: top; }}
th.line {{ text-align: left; font-weight: normal; max-width: 280px; }}
audio {{ width: 190px; }} .t {{ font-size: 12px; opacity: .7; }} .slow {{ color: #c0392b; opacity: 1; }}
.code {{ display: none; }} body.blind .name {{ display: none; }} body.blind .code {{ display: inline; }}
body.blind .t {{ visibility: hidden; }}
</style></head><body>
<h1>Swift voices</h1>
<p>Same lines, every voice, made on this PC. Red: over the 700 ms budget to start speaking.
<label><input type="checkbox" onchange="document.body.classList.toggle('blind', this.checked)"> Hide names and timings (blind listen: columns become A, B, C…)</label></p>
<table><tr><th></th>{head}</tr>{"".join(body)}</table>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="fetch the Kokoro model if missing")
    ap.add_argument("--fp32", action="store_true", help="also try the full 310 MB Kokoro model")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--kokoro-voices", default=",".join(KOKORO_PICKS))
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SPIKES_DIR / "tts" / "results" / f"voices-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    proc = psutil.Process()
    results: dict[str, dict] = {}

    def run(label: str, synth: Synth, load_s: float, ram_before: float) -> None:
        results[label] = {"load_s": round(load_s, 2), "ram_mb": round(private_mb(proc) - ram_before, 1),
                          "lines": measure(label, synth, args.reps, out)}

    for name in WINDOWS_PICKS:
        before, start = private_mb(proc), time.perf_counter()
        engine = windows_engine(name)
        if engine:
            run(engine[0], engine[1], time.perf_counter() - start, before)

    before, start = private_mb(proc), time.perf_counter()
    engine = piper_engine()
    if engine:
        run(engine[0], engine[1], time.perf_counter() - start, before)

    models = [(KOKORO_INT8, "")] + ([(KOKORO_FP32, " (fp32)")] if args.fp32 else [])
    files_sha: dict[str, str] = {}
    for model, label in models:
        files = kokoro_files(model, args.download)
        if not files:
            continue
        files_sha.update({p.name: sha256(p) for p in files})
        before, start = private_mb(proc), time.perf_counter()
        try:
            _, for_voice = kokoro_engine(*files, label)
        except ImportError:
            print("kokoro: kokoro-onnx not installed; run with `--with kokoro-onnx==0.6.1`")
            break
        load_s = time.perf_counter() - start
        for name in args.kokoro_voices.split(","):
            vlabel, synth = for_voice(name.strip())
            run(vlabel, synth, load_s, before)

    (out / "index.html").write_text(page(results, stamp), encoding="utf-8")
    write_result("tts", "voices", {
        "reps": args.reps,
        "lines": LINES,
        "kokoro_files_sha256": files_sha,
        "method": "warm; first audio = first sentence ready (Kokoro, Piper) or whole line (SAPI to file); "
                  "medians over reps; ram_mb = private bytes growth when the engine loaded",
        "voices": results,
    })
    print(f"\nlisten: {out / 'index.html'}")
    print(json.dumps({v: max(r["first_audio_s"] for r in d["lines"].values()) for v, d in results.items()}, indent=1))


if __name__ == "__main__":
    main()

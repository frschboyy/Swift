"""S2: Piper time-to-first-audio, real-time factor, and STT test clips.

Usage:  uv run --group spikes python spikes/latency/piper_bench.py [--reps 30]

Downloads one voice (with MODEL_CARD) into %LOCALAPPDATA%\\Swift\\models\\piper,
records SHA-256s, then measures:
  - voice load time
  - time to first audio chunk (TTFA) and full synthesis time for three
    response lengths, warm, n=--reps each
  - real-time factor (synthesis time / audio duration)
It also writes 2/5/10 s speech clips (padded with trailing silence to the
exact length) to spikes/latency/results/clips for stt_bench.py.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _util import SPIKES_DIR, Timer, models_dir, summarize, write_result  # noqa: E402

VOICE = "en_US-lessac-medium"
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
FILES = [f"{VOICE}.onnx", f"{VOICE}.onnx.json", "MODEL_CARD"]

RESPONSES = {
    "short": "Draft saved.",
    "typical": "I found a free slot on Tuesday at two PM your time. Should I send the invite?",
    "long": (
        "The latest report is status update October dot PDF. It lists three outstanding issues: "
        "the data pipeline fails on empty files, the figures in chapter four are out of date, "
        "and the supervisor has not yet approved the ethics form."
    ),
}

# Texts sized to fit inside each clip; padded with silence to the exact length.
CLIP_TEXTS = {
    2: "Open my project.",
    5: "Hey Swift, remind me every Friday to send my supervisor an update.",
    10: (
        "Draft an email to my dean explaining that the lab results are delayed by two weeks "
        "because the equipment was out of service, and ask for a short extension."
    ),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, target: Path, attempts: int = 5) -> None:
    """Download to <target>.part and rename only when complete, so a truncated file is never used."""
    part = target.with_name(target.name + ".part")
    for attempt in range(1, attempts + 1):
        print(f"downloading {target.name} (attempt {attempt}) ...")
        try:
            urllib.request.urlretrieve(url, part)
            part.replace(target)
            return
        except (urllib.error.ContentTooShortError, OSError) as exc:
            print(f"  incomplete: {exc}")
            part.unlink(missing_ok=True)
            time.sleep(5 * attempt)
    raise SystemExit(f"could not download {url}")


def ensure_voice() -> tuple[Path, dict[str, str]]:
    d = models_dir() / "piper" / VOICE
    d.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for name in FILES:
        target = d / name
        if not target.exists():
            download(f"{HF_BASE}/{name}", target)
        manifest[name] = sha256(target)
    return d / f"{VOICE}.onnx", manifest


def synth(voice, text: str) -> tuple[float, float, np.ndarray, int]:
    """Return (ttfa_s, total_s, int16 audio, sample_rate)."""
    chunks: list[np.ndarray] = []
    ttfa = None
    rate = 0
    with Timer() as t:
        for chunk in voice.synthesize(text):
            if ttfa is None:
                ttfa = time.perf_counter() - t.start
            rate = chunk.sample_rate
            chunks.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))
    return float(ttfa or t.elapsed), t.elapsed, np.concatenate(chunks), rate


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=30)
    args = ap.parse_args()

    from piper import PiperVoice

    model_path, manifest = ensure_voice()
    card = (model_path.parent / "MODEL_CARD").read_text(encoding="utf-8", errors="replace")

    with Timer() as load:
        voice = PiperVoice.load(str(model_path))
    synth(voice, "Warm up.")  # first call allocates the ONNX session buffers

    results: dict[str, dict] = {}
    for name, text in RESPONSES.items():
        ttfa, total, rtf = [], [], []
        for _ in range(args.reps):
            a, b, audio, rate = synth(voice, text)
            ttfa.append(a)
            total.append(b)
            rtf.append(b / (len(audio) / rate))
        results[name] = {
            "chars": len(text),
            "audio_s": round(len(audio) / rate, 2),
            "ttfa_s": summarize(ttfa),
            "total_s": summarize(total),
            "rtf": summarize(rtf),
        }
        print(name, results[name]["ttfa_s"], "rtf p50", results[name]["rtf"]["p50"])

    clip_dir = SPIKES_DIR / "latency" / "results" / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clips = {}
    for seconds, text in CLIP_TEXTS.items():
        _, _, audio, rate = synth(voice, text)
        speech_s = len(audio) / rate
        target = int(seconds * rate)
        if len(audio) < target:
            audio = np.concatenate([audio, np.zeros(target - len(audio), dtype=np.int16)])
        path = clip_dir / f"clip_{seconds}s.wav"
        write_wav(path, audio, rate)
        clips[f"{seconds}s"] = {"path": str(path), "speech_s": round(speech_s, 2), "total_s": round(len(audio) / rate, 2)}
        print(f"clip {seconds}s: speech {speech_s:.2f}s")

    write_result(
        "latency",
        "piper",
        {
            "voice": VOICE,
            "files_sha256": manifest,
            "model_card_head": card[:1500],
            "load_s": round(load.elapsed, 3),
            "reps": args.reps,
            "responses": results,
            "clips": clips,
            "method": "warm, sequential, PiperVoice.synthesize streaming; TTFA = first AudioChunk",
        },
    )


if __name__ == "__main__":
    main()

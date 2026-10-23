"""Build a personal STT test set: recordings plus the words actually said.

Usage (from the repo root):
  uv run --group sttbench python spikes/stt/corpus.py read [--prompts spikes/stt/prompts.txt]
  uv run --group sttbench python spikes/stt/corpus.py label
  uv run --group sttbench python spikes/stt/corpus.py list

read   Shows each sentence in prompts.txt; you read it aloud. Recording starts
       before you speak and stops when you press Enter, so nothing is clipped.
label  Goes through push-to-talk recordings Swift saved (stt.save_audio: true),
       plays each one with Swift's transcript, and asks for the correct text.
list   Counts what's in the test set.

Everything lives in %LOCALAPPDATA%\\Swift\\stt_corpus (clips/*.wav + refs.jsonl),
never in git: it's your voice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
SWIFT_DIR = Path(os.environ["LOCALAPPDATA"]) / "Swift"
CORPUS_DIR = Path(os.environ.get("SWIFT_STT_CORPUS") or SWIFT_DIR / "stt_corpus")
REFS = CORPUS_DIR / "refs.jsonl"
DEFAULT_PROMPTS = Path(__file__).resolve().parent / "prompts.txt"


def load_refs() -> list[dict]:
    if not REFS.exists():
        return []
    return [json.loads(line) for line in REFS.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_ref(row: dict) -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    with REFS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: expected 16 kHz mono int16")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.astype(np.int16).tobytes())


def _input_device():
    """Same device choice as Swift: WASAPI's default input."""
    import sounddevice as sd

    for api in sd.query_hostapis():
        if api["name"] == "Windows WASAPI" and api["default_input_device"] >= 0:
            return api["default_input_device"], sd.WasapiSettings(auto_convert=True)
    return None, None


def record_until_enter() -> np.ndarray:
    import sounddevice as sd

    blocks: list[np.ndarray] = []
    device, extra = _input_device()
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=512,
        device=device, extra_settings=extra, callback=lambda d, *_: blocks.append(d.copy()),
    )
    with stream:
        input("  (recording... press Enter when done) ")
    return np.concatenate(blocks).reshape(-1) if blocks else np.zeros(0, dtype=np.int16)


def play(audio: np.ndarray) -> None:
    import sounddevice as sd

    sd.play(audio, SAMPLE_RATE)
    sd.wait()


def peak_db(audio: np.ndarray) -> float:
    x = audio.astype(np.float32) / 32768.0
    n = len(x) // 512 * 512
    if n == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(x[:n].reshape(-1, 512) ** 2, axis=1)).max())
    return round(20 * np.log10(rms), 1) if rms > 1e-6 else -120.0


def cmd_read(args: argparse.Namespace) -> None:
    prompts = [
        line.strip() for line in Path(args.prompts).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    done = {r["ref"] for r in load_refs() if r["source"] == "read"}
    todo = [p for p in prompts if p not in done]
    print(f"{len(prompts) - len(todo)} of {len(prompts)} already recorded. Speak at your normal pace and volume.")
    print("For each sentence: Enter = start recording, s = skip, q = quit.\n")
    for i, text in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {text}")
        while True:
            choice = input("  Enter to record> ").strip().lower()
            if choice == "q":
                return
            if choice == "s":
                break
            audio = record_until_enter()
            level = peak_db(audio)
            print(f"  {len(audio) / SAMPLE_RATE:.1f} s, peak {level} dBFS")
            if level < -50:
                print("  That was nearly silent; check the mic and try again.")
                continue
            keep = input("  Enter = keep, p = play back, r = redo> ").strip().lower()
            while keep == "p":
                play(audio)
                keep = input("  Enter = keep, p = play back, r = redo> ").strip().lower()
            if keep == "r":
                continue
            clip_id = f"read-{len(load_refs()) + 1:04d}"
            write_wav(CORPUS_DIR / "clips" / f"{clip_id}.wav", audio)
            append_ref({"id": clip_id, "wav": f"clips/{clip_id}.wav", "ref": text, "source": "read"})
            break
    print(f"\nDone. {len(load_refs())} clips in {CORPUS_DIR}")


def _swift_transcripts() -> dict[str, str]:
    log = SWIFT_DIR / "interactions.jsonl"
    out: dict[str, str] = {}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[row.get("id", "")] = row.get("transcript") or ""
    return out


def cmd_label(args: argparse.Namespace) -> None:
    audio_dir = Path(args.audio_dir)
    seen = {r["id"] for r in load_refs()}
    wavs = sorted(p for p in audio_dir.glob("*.wav") if f"swift-{p.stem}" not in seen) if audio_dir.exists() else []
    if not wavs:
        print(f"No new recordings in {audio_dir}. Turn on stt.save_audio in config.yaml and use Swift for a while.")
        return
    transcripts = _swift_transcripts()
    print(f"{len(wavs)} new recordings. For each one, after it plays:")
    print("  Enter = Swift's transcript was right; type the correct text otherwise;")
    print("  p = play again, x = not speech (drop), s = skip for now, q = quit.\n")
    for i, path in enumerate(wavs, 1):
        audio = read_wav(path)
        hyp = transcripts.get(path.stem, "")
        print(f"[{i}/{len(wavs)}] {len(audio) / SAMPLE_RATE:.1f} s   Swift heard: {hyp or '(nothing)'}")
        play(audio)
        while True:
            answer = input("  correct text> ").strip()
            if answer.lower() == "p":
                play(audio)
                continue
            break
        if answer.lower() == "q":
            return
        if answer.lower() == "s":
            continue
        clip_id = f"swift-{path.stem}"
        if answer.lower() == "x":
            append_ref({"id": clip_id, "wav": str(path), "ref": None, "source": "swift", "swift_hyp": hyp})
            continue
        ref = answer or hyp
        if not ref:
            print("  No text given and Swift heard nothing; skipped.")
            continue
        dest = CORPUS_DIR / "clips" / f"{clip_id}.wav"
        write_wav(dest, audio)
        append_ref({"id": clip_id, "wav": f"clips/{clip_id}.wav", "ref": ref, "source": "swift", "swift_hyp": hyp})
    print(f"\nDone. {len(load_refs())} entries in {REFS}")


def cmd_list(_args: argparse.Namespace) -> None:
    refs = [r for r in load_refs() if r.get("ref")]
    total_s = 0.0
    for r in refs:
        with wave.open(str(CORPUS_DIR / r["wav"]), "rb") as w:
            total_s += w.getnframes() / w.getframerate()
    by_source: dict[str, int] = {}
    for r in refs:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"{len(refs)} clips, {total_s / 60:.1f} min of speech, by source: {by_source}")
    print(f"Folder: {CORPUS_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_read = sub.add_parser("read", help="record yourself reading prompts")
    p_read.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    p_read.set_defaults(fn=cmd_read)
    p_label = sub.add_parser("label", help="correct transcripts of Swift's saved recordings")
    p_label.add_argument("--audio-dir", default=str(SWIFT_DIR / "audio"))
    p_label.set_defaults(fn=cmd_label)
    sub.add_parser("list", help="summarize the test set").set_defaults(fn=cmd_list)
    args = ap.parse_args()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        print("\nStopped. Everything recorded so far is saved.")
        sys.exit(130)


if __name__ == "__main__":
    main()

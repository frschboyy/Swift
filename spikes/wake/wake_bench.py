"""Wake bench: today's speech-to-text wake matching vs a dedicated wake-word model, on the owner's own clips.

ADR-020 decision 2. Nothing here is imported by src/swift, and nothing leaves the PC: audio is
copied into --out (outside git), transcribed locally with Parakeet, and scored locally.

  build  copy the owner's saved clips into --out and write manifest.jsonl (ids, labels, durations; no text)
  stt    transcribe every clip with Parakeet (+ the owner's word fixes) and score swift.wake.match_wake
  align  when the name ends in each positive clip (Parakeet's token times), for the latency column
  oww    stream every clip through openWakeWord and score it (needs a model: --model NAME_OR_PATH)
  viola  stream every clip through a ViolaWake model (--model PATH.onnx), scored like oww
  porcupine  stream every clip through legacy Porcupine 1.9 (built-in keywords, no AccessKey)
  stage2 transcribe the window each detector fired on, for the two-stage rows
  report print the comparison from the files the other steps wrote: each detector alone, and as stage 1
         of a two-stage wake (detector fires, then Parakeet + a lenient "... swift" check on that window)

Labels. pos: the clip opens with a wake phrase. neg: it doesn't. "wake" clips were started by wake listening,
so today's path accepted them (selection bias: they can't count as today's misses). "wake_miss" clips have no
ground truth; they are labelled by hand in --labels (id -> pos/neg/skip) from two local transcripts
(Parakeet and Whisper small.en, see `stt --whisper`). Read-aloud corpus clips are labelled from their reference text.

  uv run --frozen --group spikes python spikes/wake/wake_bench.py build --out <scratch>
  uv run --frozen --group spikes python spikes/wake/wake_bench.py stt --out <scratch> --whisper
  uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/wake_bench.py oww --out <scratch> --model hey_jarvis
  uv run --frozen --group spikes python spikes/wake/wake_bench.py report --out <scratch> --labels <labels.json>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import wave
from pathlib import Path

import numpy as np

RATE = 16_000
SWIFT = Path(os.environ.get("SWIFT_DATA", "//localhost/c$/Users/frchi/AppData/Local/Swift"))
CHUNK = 1280  # openWakeWord's 80 ms frame


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(audio.tobytes())


def utterances(audio: np.ndarray) -> list[np.ndarray]:
    """Cut a long recording the way live wake listening does (swift.wake.WakeListener, its defaults)."""
    from swift.audio.recorder import BLOCK
    from swift.wake import WakeListener

    out: list[np.ndarray] = []
    listener = WakeListener(lambda utt, ended_at, *short: out.append(utt))
    for j in range(0, len(audio) - BLOCK + 1, BLOCK):
        listener.feed(audio[j:j + BLOCK])
    return out


# ---- build -------------------------------------------------------------------------------------------

def build(out: Path) -> None:
    from swift.wake import match_wake

    clips = out / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    def add(src: Path, cid: str, source: str, label: str, basis: str, ts: float | None = None) -> None:
        if not src.exists():
            return
        dst = clips / f"{cid}.wav"
        if not dst.exists():
            shutil.copyfile(src, dst)
        rows.append({"id": cid, "source": source, "label": label, "basis": basis, "ts": ts,
                     "audio_s": round(len(read_wav(dst)) / RATE, 2)})

    index = json.loads((SWIFT / "audio" / "index.json").read_text(encoding="utf-8"))["clips"]
    for c in index:
        src = SWIFT / "audio" / f"{c['id']}.wav"
        if c["source"] == "wake":
            add(src, c["id"], "wake", "pos", "started by wake listening", c["ts"])
            # The request after the phrase is ordinary speech: from 3 s on, a negative.
            if src.exists() and len(audio := read_wav(src)) > 5 * RATE:
                tail = clips / f"{c['id']}-tail.wav"
                with wave.open(str(tail), "wb") as w:
                    w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
                    w.writeframes(audio[3 * RATE:].tobytes())
                add(tail, f"{c['id']}-tail", "wake_tail", "neg", "a wake clip from 3 s on", c["ts"])
        elif c["source"] == "wake_miss":
            add(src, c["id"], "wake_miss", "unknown", "hand label", c["ts"])
        elif c["source"] in ("voice", "followup"):
            add(src, c["id"], c["source"], "neg", "hotkey or answer, no wake phrase expected", c["ts"])
    for folder in ("stt_corpus", "stt_noisy"):
        for r in load_jsonl(SWIFT / folder / "refs.jsonl"):
            if not r.get("ref"):
                continue
            label = "pos" if match_wake(r["ref"]) else "neg"
            add(SWIFT / folder / r["wav"], f"{folder}-{r['id']}", folder, label, "reference text")
    # The owner's recorded takes (spikes/wake/record_corpus.py), with or without a request. Other phrases
    # ("Jarvis") are kept apart: `report --phrase jarvis` scores them, and they're neither label otherwise.
    takes = SWIFT / "corpus" / "wake" / "positives"
    if (takes / "manifest.csv").exists():
        with open(takes / "manifest.csv", newline="", encoding="utf-8") as f:
            for t in csv.DictReader(f):
                hey_swift = match_wake(t["phrase"]) is not None
                add(takes / t["file"], f"take-{Path(t['file']).stem}", "take" if hey_swift else "other_take",
                    "pos" if hey_swift else t["phrase"].strip().lower(), f"recorded as {t['phrase']}")
    # Room recordings (spikes/wake/record_negatives.py), cut into utterances by Swift's own WakeListener, as
    # live: that's what today's path sees. Each utterance carries its share of the recording's length, so
    # false wakes are per hour of room time, not per hour of speech.
    room = SWIFT / "corpus" / "wake" / "negatives"
    if (room / "manifest.csv").exists():
        pending = 0.0  # seconds of chunks with no speech at all, carried to the next utterances
        with open(room / "manifest.csv", newline="", encoding="utf-8") as f:
            for c in csv.DictReader(f):
                n = len(rows)
                for k, utt in enumerate(utterances(read_wav(room / c["file"]))):
                    cid = f"room-{Path(c['file']).stem}-{k:04d}"
                    write_wav(clips / f"{cid}.wav", utt)
                    add(clips / f"{cid}.wav", cid, "room", "neg", f"room recording: {c['label']}")
                pending += float(c["seconds"])
                for r in rows[n:]:
                    r["covers_s"] = round(pending / (len(rows) - n), 2)
                pending = 0.0 if len(rows) > n else pending
        if pending and (last := [r for r in rows if r["source"] == "room"]):
            last[-1]["covers_s"] += round(pending, 2)
    seen = {r["id"] for r in rows}
    for c in json.loads((SWIFT / "stt_testset" / "index.json").read_text(encoding="utf-8"))["clips"]:
        if c["id"] not in seen and c.get("known"):
            label = "pos" if match_wake(c["known"]) else "neg"
            add(SWIFT / "stt_testset" / c["wav"], c["id"], "stt_testset", label, "reference text")
    save_jsonl(out / "manifest.jsonl", rows)
    by = {}
    for r in rows:
        by.setdefault((r["source"], r["label"]), [0, 0.0])
        by[(r["source"], r["label"])][0] += 1
        by[(r["source"], r["label"])][1] += r["audio_s"]
    for (s, lab), (n, secs) in sorted(by.items()):
        print(f"{s:12} {lab:8} {n:4} clips {secs / 60:6.1f} min")


# ---- stt: today's path -------------------------------------------------------------------------------

def stt(out: Path, whisper: bool) -> None:
    import psutil

    from swift.stt.fixes import WordFixes
    from swift.stt.transcriber import ParakeetTranscriber, WhisperTranscriber

    rows = load_jsonl(out / "manifest.jsonl")
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    stt = ParakeetTranscriber(SWIFT / "models", cpu_threads=4, fixes=WordFixes.load(SWIFT / "word_fixes.json"))
    stt._load()
    if stt._error is not None:
        sys.exit(f"{stt._error} {stt._error.hint}")
    rss_loaded = proc.memory_info().rss
    cpu0, wall0 = proc.cpu_times(), time.perf_counter()
    for i, r in enumerate(rows, 1):
        print(f"\rparakeet {i}/{len(rows)}", end="", flush=True)
        t = stt._transcribe_sync(read_wav(out / "clips" / f"{r['id']}.wav"))
        r["parakeet"], r["parakeet_ms"] = t.text, t.stt_ms
    cpu1 = proc.cpu_times()
    audio_s = sum(r["audio_s"] for r in rows)
    perf = {"model_mb": round((rss_loaded - rss0) / 2**20), "peak_rss_mb": round(proc.memory_info().rss / 2**20),
            "cpu_s": round(cpu1.user + cpu1.system - cpu0.user - cpu0.system, 1),
            "wall_s": round(time.perf_counter() - wall0, 1), "audio_s": round(audio_s, 1)}
    print("\n", perf)
    if whisper:  # a second opinion for hand-labelling the misses only
        w = WhisperTranscriber("small.en", SWIFT / "models" / "whisper", cpu_threads=4)
        w._load()
        for r in rows:
            if r["source"] == "wake_miss":
                r["whisper"] = w._transcribe_sync(read_wav(out / "clips" / f"{r['id']}.wav")).text
    save_jsonl(out / "stt.jsonl", rows)
    (out / "stt_perf.json").write_text(json.dumps(perf), encoding="utf-8")


# ---- oww: the candidate ------------------------------------------------------------------------------

def oww(out: Path, model: str, tag: str) -> None:
    import psutil
    from openwakeword.model import Model

    rows = load_jsonl(out / "manifest.jsonl")
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    m = Model(wakeword_models=[model], inference_framework="onnx")
    name = next(iter(m.models))
    rss_loaded = proc.memory_info().rss
    cpu0, wall0 = proc.cpu_times(), time.perf_counter()
    for i, r in enumerate(rows, 1):
        print(f"\roww {i}/{len(rows)}", end="", flush=True)
        m.reset()
        audio = read_wav(out / "clips" / f"{r['id']}.wav")
        # 1 s of silence first so the model's feature buffer is warm, as it would be when streaming.
        audio = np.concatenate([np.zeros(RATE, np.int16), audio, np.zeros(RATE // 2, np.int16)])
        scores = [m.predict(audio[j:j + CHUNK])[name] for j in range(0, len(audio) - CHUNK + 1, CHUNK)]
        r["scores"] = [round(float(s), 4) for s in scores]  # one per 80 ms, the first second is padding
    cpu1 = proc.cpu_times()
    perf = {"model_mb": round((rss_loaded - rss0) / 2**20), "peak_rss_mb": round(proc.memory_info().rss / 2**20),
            "cpu_s": round(cpu1.user + cpu1.system - cpu0.user - cpu0.system, 1),
            "wall_s": round(time.perf_counter() - wall0, 1),
            "audio_s": round(sum(r["audio_s"] + 1.5 for r in rows), 1)}
    print("\n", perf)
    save_jsonl(out / f"oww_{tag}.jsonl", [{"id": r["id"], "scores": r["scores"]} for r in rows])
    (out / f"oww_{tag}_perf.json").write_text(json.dumps(perf), encoding="utf-8")


def viola(out: Path, model: str, tag: str) -> None:
    """ViolaWake: its detector scores 20 ms frames; kept as the max per 80 ms, in oww's format and timing."""
    import psutil
    from violawake_sdk import WakeDetector

    rows = load_jsonl(out / "manifest.jsonl")
    proc = psutil.Process()
    cpu0, wall0, res = proc.cpu_times(), time.perf_counter(), []
    for i, r in enumerate(rows, 1):
        print(f"\rviola {i}/{len(rows)}", end="", flush=True)
        det = WakeDetector(model=model, threshold=0.99, confirm_count=1)  # fresh state per clip
        audio = np.concatenate([np.zeros(RATE, np.int16), read_wav(out / "clips" / f"{r['id']}.wav"),
                                np.zeros(RATE // 2, np.int16)])
        frames = [det.process(audio[j:j + 320]) for j in range(0, len(audio) - 320 + 1, 320)]
        res.append({"id": r["id"], "scores": [round(float(max(frames[k:k + 4])), 4)
                                              for k in range(0, len(frames) - 3, 4)]})
    cpu1 = proc.cpu_times()
    perf = {"model_mb": 0, "peak_rss_mb": round(proc.memory_info().rss / 2**20),
            "cpu_s": round(cpu1.user + cpu1.system - cpu0.user - cpu0.system, 1),
            "wall_s": round(time.perf_counter() - wall0, 1), "audio_s": round(sum(r["audio_s"] + 1.5 for r in rows), 1)}
    print("\n", perf)
    save_jsonl(out / f"oww_{tag}.jsonl", res)
    (out / f"oww_{tag}_perf.json").write_text(json.dumps(perf), encoding="utf-8")


# ---- porcupine: an acoustic detector with built-in keywords ------------------------------------------

def porcupine(out: Path, keyword: str, sens: list[float], tag: str) -> None:
    """Legacy Porcupine 1.9 (no AccessKey, nothing online): a built-in keyword name or a .ppn path.
    One handle per sensitivity; a hit is the first frame it fires on, in seconds from the clip's start."""
    import psutil
    import pvporcupine

    rows = load_jsonl(out / "manifest.jsonl")
    kw = {"keyword_paths": [keyword]} if keyword.endswith(".ppn") else {"keywords": [keyword]}
    handles = {str(s): pvporcupine.create(sensitivities=[s], **kw) for s in sens}
    n = next(iter(handles.values())).frame_length
    proc = psutil.Process()
    cpu0, res = proc.cpu_times(), []
    for i, r in enumerate(rows, 1):
        print(f"\rporcupine {i}/{len(rows)}", end="", flush=True)
        audio = np.concatenate([np.zeros(RATE, np.int16), read_wav(out / "clips" / f"{r['id']}.wav"),
                                np.zeros(RATE // 2, np.int16)])
        hits = {}
        for s, h in handles.items():
            fired = [j for j in range(0, len(audio) - n + 1, n) if h.process(audio[j:j + n]) >= 0]
            hits[s] = round((fired[0] + n) / RATE - 1.0, 3) if fired else None
        res.append({"id": r["id"], "hits": hits})
    cpu1 = proc.cpu_times()
    perf = {"model_mb": 0, "peak_rss_mb": round(proc.memory_info().rss / 2**20),
            "cpu_s": round((cpu1.user + cpu1.system - cpu0.user - cpu0.system) / len(handles), 1),
            "audio_s": round(sum(r["audio_s"] + 1.5 for r in rows), 1)}
    print("\n", perf)
    save_jsonl(out / f"porcupine_{tag}.jsonl", res)
    (out / f"porcupine_{tag}_perf.json").write_text(json.dumps(perf), encoding="utf-8")


def align(out: Path, labels: Path | None) -> None:
    """When the name ends in each positive clip (Parakeet's token times), for the latency column."""
    import onnx_asr

    from train_head import swift_end

    path = out / "align.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", SWIFT / "models" / "parakeet-tdt-0.6b-v2",
                              quantization="int8").with_timestamps()
    for r in labelled(out, labels):
        if r["label"] == "pos" and r["id"] not in done:
            done[r["id"]] = swift_end(asr, read_wav(out / "clips" / f"{r['id']}.wav"))
    path.write_text(json.dumps(done))


# ---- report ------------------------------------------------------------------------------------------

def labelled(out: Path, labels: Path | None, phrase: str | None = None) -> list[dict]:
    """Clips labelled pos/neg. With `phrase` (e.g. "jarvis"), its recorded takes are the positives and every
    "Hey Swift" clip becomes a negative: the detector for that word must not fire on them."""
    rows = load_jsonl(out / "stt.jsonl")
    hand = json.loads(labels.read_text(encoding="utf-8")) if labels else {}
    for r in rows:
        if r["id"] in hand:
            r["label"] = hand[r["id"]]
        if phrase:
            r["label"] = "pos" if r["label"] == phrase.lower() else "neg" if r["label"] == "pos" else r["label"]
    return [r for r in rows if r["label"] in ("pos", "neg")]


def stt_scores(rows: list[dict]) -> dict:
    from swift.wake import match_wake

    res = {}
    for mode, loose in (("strict", False), ("loose", True)):
        fired = {r["id"]: match_wake(r["parakeet"], loose=loose) is not None for r in rows}
        res[mode] = fired
    return res


def summary(rows: list[dict], fired: dict[str, bool], name: str) -> str:
    pos = [r for r in rows if r["label"] == "pos"]
    neg = [r for r in rows if r["label"] == "neg"]
    miss = [r for r in pos if not fired[r["id"]]]
    fa = [r for r in neg if fired[r["id"]]]
    neg_h = sum(r.get("covers_s", r["audio_s"]) for r in neg) / 3600
    by_src = {}
    for r in miss:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    live = [r for r in pos if r["source"] == "wake_miss"]
    takes = [r for r in pos if r["source"] in ("calm_take", "take", "other_take")]
    room = [r for r in neg if r["source"] == "room"]
    room_line = ""
    if room:
        room_h = sum(r["covers_s"] for r in room) / 3600
        room_line = f" (room: {sum(fired[r['id']] for r in room)} in {room_h:.1f} h)"
    return (f"{name:34} misses {len(miss):3}/{len(pos):3} ({100 * len(miss) / max(len(pos), 1):4.1f}%)"
            f" | live misses caught {sum(fired[r['id']] for r in live)}/{len(live)}"
            f" | takes {sum(fired[r['id']] for r in takes)}/{len(takes)}"
            f" | false wakes {len(fa):2}/{len(neg)} clips = {len(fa) / neg_h:5.1f}/h{room_line}  {by_src}")


# Stage 2 of a two-stage wake: run only after an acoustic detector fired, so it can be lenient. What Parakeet
# writes for a calm "Hey Swift" in the office: "He swift", "Eat swift", "Very swift", "He swiftly" (2026-11-10).
SOUNDS_LIKE_A_GREETING = ("hey", "hay", "he", "hi", "high", "a", "eh", "eat", "heat", "hate", "they", "very",
                          "okay", "ok", "hello", "oh", "say")
_LENIENT = re.compile(rf"\b(?:{'|'.join(SOUNDS_LIKE_A_GREETING)})\W+(?:swift|swiftly|swifts|twift|twif)\b"
                      # or something before a "wift" word at the start: "Exwift", "He dwifts", "Pretty swift"
                      # (the bare name, "Swift." or "Swift, yes", is a known hard negative)
                      r"|^\W*(?:[\w']+\W+[\w']*|(?!s?wift)[\w']+)wift(?:s|ly)?\b")


def lenient_wake(text: str) -> bool:
    from swift.wake import match_wake

    return bool(_LENIENT.search(text.lower())) or match_wake(text, loose=True) is not None


def check_lenient() -> None:
    for text in ("He swift.", "Eat swift", "Very swift", "He swiftly", "Exwift.", "He dwifts.", "Pretty swift."):
        assert lenient_wake(text), text
    for text in ("Nice work", "I think Swift is crazy", "He drifted.", "the report was done swiftly and then",
                 "Swift.", "Swift, yes.", "Swiftly done."):
        assert not lenient_wake(text), text


# (seconds of audio, ending this many seconds past the detection). Trained heads can fire on "hey s-",
# about 1 s before the name ends, so one window runs on past it; live, that one adds 1 s.
STAGE2_WINDOWS = ((1.2, 0.3), (1.6, 0.3), (2.0, 1.0))


def heard_key(cid: str, t: float) -> str:
    return f"{cid}@{t:.2f}"


def stage_lines(rows: list[dict], hit: dict[str, float | None], late: list[float], name: str,
                heard: dict[str, list[str]]) -> None:
    """Stage 1 alone, then stage 1 and the lenient check on Parakeet's transcript of the window it fired on
    (any of STAGE2_WINDOWS). Without `stage2` run for this detector, the whole clip's transcript stands in."""
    fired = {r["id"]: hit[r["id"]] is not None for r in rows}
    line = summary(rows, fired, name)
    if late:
        line += f" | fires {np.median(late):+.2f} s after 'swift' ends (median)"
    print(line)
    texts = {r["id"]: heard.get(heard_key(r["id"], hit[r["id"]]), [r["parakeet"]]) if fired[r["id"]] else []
             for r in rows}
    windowed = all(heard_key(r["id"], hit[r["id"]]) in heard for r in rows if fired[r["id"]])
    two = {r["id"]: any(lenient_wake(t) for t in texts[r["id"]]) for r in rows}
    print(summary(rows, two, f"  + parakeet lenient ({'window' if windowed else 'whole clip'})"))


def detections(out: Path, rows: list[dict], tags: list[str], thresholds: list[float], patience: int,
               porcupine_tags: list[str]):
    """(name, {clip id: seconds from the clip's start when stage 1 first fired, or None}) per setting."""
    for tag in tags:
        res = {r["id"]: r for r in load_jsonl(out / f"oww_{tag}.jsonl")}
        for th in thresholds:
            hit = {}
            for r in rows:
                s = res[r["id"]]["scores"]
                # Score k covers audio up to k * 0.08 + offset s from clip start (streaming: (k+1) chunks - 1 s pad).
                offset = res[r["id"]].get("offset", 0.08 - 1.0)
                ks = [k for k in range(len(s) - patience + 1) if min(s[k:k + patience]) >= th]
                hit[r["id"]] = round((ks[0] + patience - 1) * 0.08 + offset, 2) if ks else None
            yield f"oww {tag} th={th}", hit
    for tag in porcupine_tags:
        res = {r["id"]: r["hits"] for r in load_jsonl(out / f"porcupine_{tag}.jsonl")}
        for sens in next(iter(res.values())):
            yield f"porcupine {tag} sens={sens}", {r["id"]: res[r["id"]][sens] for r in rows}


def stage2(out: Path, labels: Path | None, tags: list[str], thresholds: list[float], patience: int,
           porcupine_tags: list[str]) -> None:
    """Transcribe the windows each detector fired on, as stage 2 would live; cached in stage2.json."""
    from swift.stt.fixes import WordFixes
    from swift.stt.transcriber import ParakeetTranscriber

    path = out / "stage2.json"
    heard = json.loads(path.read_text()) if path.exists() else {}
    rows = labelled(out, labels)
    todo = {(r["id"], hit[r["id"]]) for _, hit in detections(out, rows, tags, thresholds, patience, porcupine_tags)
            for r in rows if hit[r["id"]] is not None and heard_key(r["id"], hit[r["id"]]) not in heard}
    stt = ParakeetTranscriber(SWIFT / "models", cpu_threads=4, fixes=WordFixes.load(SWIFT / "word_fixes.json"))
    stt._load()
    for i, (cid, t) in enumerate(sorted(todo), 1):
        print(f"\rstage2 {i}/{len(todo)}", end="", flush=True)
        audio = read_wav(out / "clips" / f"{cid}.wav")
        heard[heard_key(cid, t)] = [
            stt._transcribe_sync(audio[max(int((t + after - w) * RATE), 0):max(int((t + after) * RATE), 1)]).text
            for w, after in STAGE2_WINDOWS]
        if i % 50 == 0:
            path.write_text(json.dumps(heard))
    path.write_text(json.dumps(heard))
    print()


def report(out: Path, labels: Path | None, tags: list[str], thresholds: list[float], patience: int,
           porcupine_tags: list[str], phrase: str | None = None) -> None:
    check_lenient()
    rows = labelled(out, labels, phrase)
    neg_min =sum(r["audio_s"] for r in rows if r["label"] == "neg") / 60
    print(f"{sum(r['label'] == 'pos' for r in rows)} positives, {sum(r['label'] == 'neg' for r in rows)} negatives"
          f" ({neg_min:.1f} min)")
    for mode, fired in stt_scores(rows).items():
        print(summary(rows, fired, f"parakeet+match_wake {mode}"))
    print(summary(rows, {r["id"]: lenient_wake(r["parakeet"]) for r in rows}, "parakeet lenient alone"))
    align = json.loads((out / "align.json").read_text()) if (out / "align.json").exists() else {}
    heard = json.loads((out / "stage2.json").read_text()) if (out / "stage2.json").exists() else {}
    for name, hit in detections(out, rows, tags, thresholds, patience, porcupine_tags):
        late = [hit[r["id"]] - align[r["id"]] for r in rows
                if hit[r["id"]] is not None and r["label"] == "pos" and align.get(r["id"]) is not None]
        stage_lines(rows, hit, late, name, heard)
    for p in sorted([*out.glob("oww_*_perf.json"), *out.glob("porcupine_*_perf.json")]):
        perf = json.loads(p.read_text())
        print(f"   {p.stem}: {perf['cpu_s'] / perf['audio_s'] * 100:.1f}% of one core while listening,"
              f" model +{perf['model_mb']} MB, process {perf['peak_rss_mb']} MB")
    perf = json.loads((out / "stt_perf.json").read_text())
    ms = sorted(r["parakeet_ms"] for r in rows if r["label"] == "pos")
    print(f"   parakeet cost: {perf['cpu_s'] / perf['audio_s'] * 100:.1f}% of one core per second of speech,"
          f" model +{perf['model_mb']} MB, transcribe p50 {ms[len(ms) // 2]} ms after the utterance ends")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["build", "stt", "align", "oww", "viola", "porcupine", "stage2", "report"])
    ap.add_argument("--out", type=Path, required=True, help="scratch folder outside git")
    ap.add_argument("--whisper", action="store_true", help="stt: also transcribe the miss clips with Whisper")
    ap.add_argument("--model", default="hey_jarvis", help="oww: a bundled model name or an .onnx path")
    ap.add_argument("--tag", default=None, help="oww: name for the result file (default: the model's)")
    ap.add_argument("--labels", type=Path, default=None, help="report: hand labels for the miss clips")
    ap.add_argument("--oww", nargs="*", default=[], help="report: oww tags to compare")
    ap.add_argument("--thresholds", type=float, nargs="*", default=[0.3, 0.5, 0.7])
    ap.add_argument("--patience", type=int, default=1, help="report: frames in a row over the threshold")
    ap.add_argument("--keyword", default="jarvis", help="porcupine: a built-in keyword or a .ppn path")
    ap.add_argument("--sens", type=float, nargs="*", default=[0.3, 0.5, 0.7, 0.9], help="porcupine sensitivities")
    ap.add_argument("--porcupine", nargs="*", default=[], help="report: porcupine tags to compare")
    ap.add_argument("--phrase", default=None, help="report: score another wake word's takes, e.g. jarvis")
    a = ap.parse_args()
    if a.step == "build":
        build(a.out)
    elif a.step == "stt":
        stt(a.out, a.whisper)
    elif a.step == "align":
        align(a.out, a.labels)
    elif a.step == "oww":
        oww(a.out, a.model, a.tag or Path(a.model).stem)
    elif a.step == "viola":
        viola(a.out, a.model, a.tag or Path(a.model).stem)
    elif a.step == "porcupine":
        porcupine(a.out, a.keyword, a.sens, a.tag or Path(a.keyword).stem)
    elif a.step == "stage2":
        stage2(a.out, a.labels, a.oww, a.thresholds, a.patience, a.porcupine)
    else:
        report(a.out, a.labels, a.oww, a.thresholds, a.patience, a.porcupine, a.phrase)


if __name__ == "__main__":
    main()

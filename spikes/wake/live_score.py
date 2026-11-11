"""ADR-021 step 6: score the second way in as Swift runs it, through the live listener.

Each bench clip is played (in clip time, not real time) into Swift's own WakeListener and AcousticWake, with
1 s of room hiss before and 1.5 s after. Every utterance the listener cuts goes the way `Session` sends it:
Parakeet, then `match_wake` loose (today's path), and if that finds nothing, the detector's hit in that
utterance and `second_way_in`. A wake needs the words at least `wake.phrase_min_p` sure, as in the session.
A clip wakes if any of its utterances does.

Writes <out>/live.jsonl and prints wake_bench's rows for today's path and for today OR the second way in.
Not replayed: the session's state (a run in front, questions, the near-miss second chance, held utterances).

  uv run --frozen --group spikes python spikes/wake/live_score.py --out <bench> --labels <labels.json> \
      --models %LOCALAPPDATA%\\Swift\\models\\wake
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from wake_bench import RATE, SWIFT, labelled, load_jsonl, read_wav, save_jsonl, summary

from swift.audio.recorder import BLOCK
from swift.stt.fixes import WordFixes
from swift.stt.transcriber import ParakeetTranscriber
from swift.wake import WakeListener, match_wake
from swift.wake_acoustic import AcousticWake, HeySwiftScorer, second_way_in

PHRASE_MIN_P = 0.2  # settings.wake.phrase_min_p


def sure(heard) -> bool:  # noqa: ANN001
    return heard.mean_p is None or heard.mean_p >= PHRASE_MIN_P


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()

    rows = labelled(a.out, a.labels)
    path = a.out / "live.jsonl"
    done = {r["id"]: r for r in load_jsonl(path)} if path.exists() else {}
    stt = ParakeetTranscriber(SWIFT / "models", cpu_threads=4, fixes=WordFixes.load(SWIFT / "word_fixes.json"))
    stt._load()
    acoustic = AcousticWake(HeySwiftScorer(a.models), threshold=a.threshold)
    rng = np.random.default_rng(0)
    fed = 0  # samples played so far: the clock
    utts: list[tuple[np.ndarray, float]] = []
    listener = WakeListener(lambda audio, _at, *short: utts.append((audio, fed / RATE)))

    for i, r in enumerate(rows, 1):
        if r["id"] in done:
            continue
        print(f"\rlive {i}/{len(rows)}", end="", flush=True)
        listener.reset()
        acoustic.reset()
        utts.clear()
        audio = np.concatenate([rng.normal(0, 8, RATE).astype(np.int16), read_wav(a.out / "clips" / f"{r['id']}.wav"),
                                rng.normal(0, 8, int(1.5 * RATE)).astype(np.int16)])
        for j in range(0, len(audio) - BLOCK + 1, BLOCK):
            fed += BLOCK
            listener.feed(audio[j:j + BLOCK])
            acoustic.push(audio[j:j + BLOCK], at=fed / RATE)
            if j % (BLOCK * 100) == 0:
                acoustic.wait_idle()  # the microphone comes in real time; never fill the queue here
        acoustic.wait_idle()
        today = second = False
        for utt, ended_at in utts:
            started_at = ended_at - len(utt) / RATE
            heard = await stt.transcribe(utt)
            if match_wake(heard.text, loose=True) is not None:
                today = today or sure(heard)
                continue
            hit = acoustic.first_hit(started_at, ended_at)
            if hit is not None and (found := await second_way_in(hit, utt, started_at, stt)) is not None:
                second = second or sure(found[1] or heard)
        done[r["id"]] = {"id": r["id"], "today": today, "second": second, "utterances": len(utts)}
        if i % 25 == 0:
            save_jsonl(path, list(done.values()))
    save_jsonl(path, list(done.values()))
    acoustic.close()
    print()
    print(summary(rows, {r["id"]: done[r["id"]]["today"] for r in rows}, "today, through the listener"))
    print(summary(rows, {r["id"]: done[r["id"]]["today"] or done[r["id"]]["second"] for r in rows},
                  "today OR the second way in"))
    print(f"clips with no utterance cut: {sum(not done[r['id']]['utterances'] for r in rows)}")


if __name__ == "__main__":
    asyncio.run(main())

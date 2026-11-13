"""The speech gate: no sentence Swift got right may go wrong (seams audit W-03, remediation G).

Usage:  uv run python eval/stt/gate.py [--write]

Transcribes every labelled clip on this PC as Swift would (Parakeet, then the learned word fixes):
the read corpus, the noisy corpus and the owner's kept clips. Per clip it keeps counts only:
the words, the word errors, and whether the heard sentence routes like the known one (same
route, action, target and app), which says whether an error changed what Swift would do.

It fails (exit 1) when a clip that was exactly right in ``baseline.json`` isn't now, or one that
routed like its known sentence doesn't now. Run it before and after any change to speech
recognition; ``--write`` saves today's result as the baseline once a change is accepted.

shortcut: fixes from config.yaml's stt.word_fixes aren't applied, only the learned file; load
the settings here if the owner starts using them.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

from swift.config.paths import app_paths
from swift.routing import route
from swift.stt.fixes import WordFixes
from swift.stt.improve import edits, normalize

HERE = Path(__file__).parent
BASELINE = HERE / "baseline.json"


def meaning(text: str) -> tuple:
    r = route(text)
    return r.route, r.action, r.target, r.app


def measure(ref: str, heard: str) -> list[int]:
    """[words, word errors, 1 if it routes like the known sentence]."""
    r = normalize(ref)
    return [len(r), edits(r, normalize(heard)), int(meaning(ref) == meaning(heard))]


def compare(before: dict[str, list[int]], now: dict[str, list[int]]) -> dict[str, list[str]]:
    """Clips both runs saw that got worse: exactly right before and not now; routed alike before and not now."""
    both = sorted(set(before) & set(now))
    return {"wrong_now": [k for k in both if before[k][1] == 0 and now[k][1] > 0],
            "routes_differently_now": [k for k in both if before[k][2] and not now[k][2]]}


def clips(data: Path) -> list[tuple[str, Path, str]]:
    out: list[tuple[str, Path, str]] = []
    for name in ("stt_corpus", "stt_noisy"):
        refs = data / name / "refs.jsonl"
        if refs.exists():
            for line in refs.read_text(encoding="utf-8").splitlines():
                if line.strip() and (r := json.loads(line)).get("ref"):
                    out.append((f"{name}/{r['id']}", data / name / r["wav"], r["ref"]))
    kept = data / "stt_testset"
    if (kept / "index.json").exists():
        for c in json.loads((kept / "index.json").read_text(encoding="utf-8")).get("clips", []):
            if c.get("known") and (kept / c["wav"]).exists():
                out.append((f"stt_testset/{c['id']}", kept / c["wav"], c["known"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="save today's result as the baseline")
    ap.add_argument("--data", type=Path, default=None, help="Swift's data folder (default: the one Swift uses)")
    args = ap.parse_args()
    from swift.stt.transcriber import ParakeetTranscriber

    data = args.data or app_paths().data_dir
    stt = ParakeetTranscriber(data / "models", fixes=WordFixes.load(data / "word_fixes.json"))
    stt._load()
    if stt._model is None:
        print("The speech model didn't load.")
        return 2
    now: dict[str, list[int]] = {}
    for key, path, ref in clips(data):
        with wave.open(str(path)) as f:
            audio = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        now[key] = measure(ref, stt._transcribe_sync(audio).text)
    for name in sorted({k.split("/")[0] for k in now}):
        rows = [v for k, v in now.items() if k.startswith(name + "/")]
        words = sum(r[0] for r in rows) or 1
        print(f"{name:12} {len(rows):3} clips  exactly right {sum(r[1] == 0 for r in rows):3}  "
              f"word error rate {sum(r[1] for r in rows) / words:.3f}  routes like the known sentence {sum(r[2] for r in rows):3}")
    before = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    worse = compare(before, now)
    print(f"\nCompared with the baseline on {len(set(before) & set(now))} clips.")
    for what, keys in worse.items():
        for k in keys:
            print(f"  FAIL {what.replace('_', ' ')}: {k}")
    if args.write:
        BASELINE.write_text(json.dumps(now, indent=0, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(now)} clips to {BASELINE.name}")
    failed = any(worse.values())
    print("FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

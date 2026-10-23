"""Learn word fixes from your labeled recordings, with your approval for each one.

Usage (from the repo root, in a normal terminal):
  uv run --group sttbench python spikes/stt/learn_fixes.py            # review new fixes
  uv run --group sttbench python spikes/stt/learn_fixes.py --list     # show saved fixes

How it works:
1. Transcribes every clip in the test set (corpus.py) with Swift's configured
   engine, exactly as Swift would (silence gate, trim; no existing fixes).
2. Lines each transcript up against what you actually said and collects the
   phrases it got wrong: "tori" -> "Tauri", "lack plot code" -> "last Claude Code".
3. Drops the unsafe ones: formatting-only differences ("3"/"three",
   "summarise"/"summarize", "set up"/"setup", "do's"/"dos"), errors at the very start of a
   clip (usually the mic missing the first syllable, not a vocabulary problem),
   anything longer than three words, and any phrase you also said correctly
   somewhere in the test set.
4. Shows each remaining fix: y keeps it, n rejects it (never asked again),
   e lets you edit what it should become.

Kept fixes go to stt.word_fixes_file (default %LOCALAPPDATA%\\Swift\\word_fixes.json);
Swift loads them at startup. Real words are risky as fixes: "deadlock" -> "git log"
would also change a real "deadlock". Reject those.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import CORPUS_DIR, load_refs, read_wav  # noqa: E402
from swift.settings import load_settings  # noqa: E402

_WORD = re.compile(r"[\w']+")
NUMBERS = "zero one two three four five six seven eight nine ten eleven twelve".split()
MAX_WORDS = 3


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def compact(phrase: str) -> str:
    """Spelling-insensitive form: no spaces or apostrophes, digits for small numbers, -ize for -ise."""
    out = []
    for w in phrase.lower().replace("'", "").split():
        w = str(NUMBERS.index(w)) if w in NUMBERS else w
        out.append(re.sub(r"is(e|ed|es|ing)$", r"iz\1", w))
    return "".join(out)


def error_spans(ref_raw: str, hyp_raw: str) -> list[tuple[str, str, int]]:
    """(heard, meant, start index in hyp) for each run of differing words.

    ``meant`` keeps the reference's own casing, so "Tauri" stays capitalized.
    """
    import jiwer

    ref_tokens, hyp_tokens = words(ref_raw), words(hyp_raw)
    if not ref_tokens or not hyp_tokens:
        return []
    out = jiwer.process_words(" ".join(t.lower() for t in ref_tokens), " ".join(t.lower() for t in hyp_tokens))
    spans: list[tuple[str, str, int]] = []
    current: list = []

    def flush() -> None:
        if current:
            r0, r1 = current[0].ref_start_idx, current[-1].ref_end_idx
            h0, h1 = current[0].hyp_start_idx, current[-1].hyp_end_idx
            spans.append((" ".join(hyp_tokens[h0:h1]).lower(), " ".join(ref_tokens[r0:r1]), h0))
            current.clear()

    for chunk in out.alignments[0]:
        if chunk.type == "equal":
            flush()
        else:
            current.append(chunk)
    flush()
    return spans


def candidates(rows: list[dict], hyps: list[str]) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], str]]:
    said = " " + " | ".join(" ".join(words(r["ref"].lower())) for r in rows) + " "
    counts: Counter[tuple[str, str]] = Counter()
    example: dict[tuple[str, str], str] = {}
    for row, hyp in zip(rows, hyps):
        for heard, meant, start in error_spans(row["ref"], hyp):
            if not heard or not meant or start == 0:
                continue
            if len(heard.split()) > MAX_WORDS or len(meant.split()) > MAX_WORDS:
                continue
            if compact(heard) == compact(meant):
                continue
            if f" {heard} " in said:  # you said this phrase for real somewhere
                continue
            counts[(heard, meant)] += 1
            example.setdefault((heard, meant), f"heard: {hyp}\n      said:  {row['ref']}")
    return dict(counts), example


def load_store(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"fixes": [], "rejected": []}


def save_store(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def transcribe_all(settings, rows: list[dict]) -> list[str]:
    from swift.config.paths import app_paths
    from swift.stt.transcriber import ParakeetTranscriber, WhisperTranscriber

    cfg = settings.stt
    if cfg.engine == "parakeet":
        stt = ParakeetTranscriber(app_paths().models_dir, cpu_threads=cfg.cpu_threads)
    else:
        stt = WhisperTranscriber(
            cfg.model, app_paths().models_dir / "whisper", cpu_threads=cfg.cpu_threads,
            initial_prompt=cfg.initial_prompt, beam_size=cfg.beam_size,
        )
    stt._load()
    if stt._error is not None:
        raise SystemExit(f"{stt._error} {stt._error.hint}")
    hyps = []
    for i, row in enumerate(rows, 1):
        print(f"\rtranscribing {i}/{len(rows)} with {stt.name}", end="", flush=True)
        hyps.append(stt._transcribe_sync(read_wav(CORPUS_DIR / row["wav"])).text)
    print()
    return hyps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "config.yaml")
    ap.add_argument("--list", action="store_true", help="show saved fixes and exit")
    args = ap.parse_args()

    settings = load_settings(args.config)
    path = Path(settings.stt.word_fixes_file)
    store = load_store(path)
    if args.list:
        print(f"{path}:")
        for f in store["fixes"]:
            print(f"  {'on ' if f.get('enabled', True) else 'off'}  {f['heard']!r} -> {f['meant']!r}  (seen {f.get('count', '?')}x)")
        print(f"  {len(store['rejected'])} rejected")
        return

    rows = [r for r in load_refs() if r.get("ref")]
    if not rows:
        raise SystemExit("No labeled clips yet. Use spikes/stt/corpus.py read or label first.")
    hyps = transcribe_all(settings, rows)
    counts, example = candidates(rows, hyps)
    known = {(f["heard"], f["meant"]) for f in store["fixes"]} | {tuple(r) for r in store["rejected"]}
    new = sorted(((k, n) for k, n in counts.items() if k not in known), key=lambda kn: -kn[1])
    if not new:
        print("No new fixes to review.")
        return

    by_heard: dict[str, list[str]] = defaultdict(list)
    for (heard, meant), _ in new:
        by_heard[heard].append(meant)
    print(f"{len(new)} possible fixes. y = keep, n = reject, e = edit, s = skip for now, q = save and quit.\n")
    try:
        for (heard, meant), n in new:
            clash = " (heard the same way for different words; be careful)" if len(by_heard[heard]) > 1 else ""
            print(f"'{heard}' -> '{meant}'   seen {n}x{clash}")
            print(f"      {example[(heard, meant)]}")
            answer = input("  keep? [y/n/e/s/q] ").strip().lower()
            if answer == "q":
                break
            if answer == "e":
                meant = input(f"  '{heard}' should become: ").strip() or meant
                answer = "y"
            if answer == "y":
                store["fixes"].append({"heard": heard, "meant": meant, "count": n, "enabled": True})
            elif answer == "n":
                store["rejected"].append([heard, meant])
    except (EOFError, KeyboardInterrupt):
        print("\nStopped; keeping the answers given so far.")
    save_store(path, store)
    print(f"\nSaved {len(store['fixes'])} fixes to {path}. Restart Swift to use them.")


if __name__ == "__main__":
    main()

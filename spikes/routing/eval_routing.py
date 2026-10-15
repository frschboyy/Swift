"""S3: routing reliability: intent accuracy, slot accuracy, valid-JSON rate.

Usage:
  uv run --group spikes python spikes/routing/eval_routing.py --grammar-only
  uv run --group spikes python spikes/routing/eval_routing.py --models qwen3:1.7b qwen3.5:4b qwen3:8b

Modes per model:
  llm       every utterance goes to the LLM
  hybrid    grammar first; LLM only when the grammar abstains
Metrics:
  intent accuracy (exact), with Wilson 95 % CI
  slot accuracy on correctly-routed items: strict (normalized exact) and
    lenient (token F1 >= 0.5 for free-text slots)
  valid JSON: first attempt, and after one repair attempt
  LLM latency per call (p50/p90, model warm)
  grammar: coverage (fired / total) and precision (correct when fired)
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _util import summarize, write_result  # noqa: E402
from grammar_proto import parse as grammar_parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
INTENTS = json.loads((ROOT / "eval" / "intents.json").read_text(encoding="utf-8"))
UTTERANCES = [json.loads(line) for line in (ROOT / "eval" / "utterances.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
INTENT_SLOTS: dict[str, list[str]] = INTENTS["intents"]
ALL_SLOTS = sorted({s for slots in INTENT_SLOTS.values() for s in slots})
FREE_TEXT = set(INTENTS["free_text_slots"])

SYSTEM = """You route voice commands for a desktop assistant. Output JSON only.
Choose exactly one intent:
- draft_email: write a NEW email. recipient = person or role as spoken without "my" (e.g. "dean", "Bob Lee"); topic = what it should say, or null.
- revise_draft: change the email just drafted. instruction = the requested change (e.g. "shorter").
- send_draft: send the email that was already drafted.
- schedule_meeting: find time and create a meeting. attendee = person or role without "my"; duration_min = integer minutes or null; when = date/time phrase as spoken, or null.
- summarize_latest_document: find the latest report/document and summarize it. project = project name only if explicitly named, else null.
- open_dev_env_and_test: open the development environment AND run the tests. project as above.
- open_dev_env: open the development environment or project only. project as above.
- run_tests: run the project's tests only. project as above.
- create_reminder: text = what to be reminded of; schedule = time/recurrence phrase as spoken, or null.
- list_reminders: list existing reminders.
- cancel_reminder: target = words identifying which reminder.
- control: action = one of stop, cancel, yes, no, mute, forget, help.
- get_time: current time. get_date: current date or weekday.
- generic: anything else, including questions about existing emails or calendar, other apps, files, or general knowledge.
All slot keys must be present; use null for slots that do not apply to the chosen intent.
Ignore a leading wake phrase such as "Hey Swift"."""


def schema() -> dict:
    props: dict[str, dict] = {}
    for s in ALL_SLOTS:
        if s == "duration_min":
            props[s] = {"type": ["integer", "null"]}
        elif s == "action":
            props[s] = {"type": ["string", "null"], "enum": [*INTENTS["control_actions"], None]}
        else:
            props[s] = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(INTENT_SLOTS)},
            "slots": {"type": "object", "properties": props, "required": ALL_SLOTS, "additionalProperties": False},
        },
        "required": ["intent", "slots"],
        "additionalProperties": False,
    }


def validate(raw: str) -> tuple[dict | None, str | None]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(obj, dict) or obj.get("intent") not in INTENT_SLOTS:
        return None, f"intent must be one of {list(INTENT_SLOTS)}"
    if not isinstance(obj.get("slots"), dict):
        return None, "slots must be an object"
    return obj, None


def norm(v: object) -> str | int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    s = str(v).lower().strip()
    if s in ("", "null", "none"):
        return None
    s = re.sub(r"[^\w\s']", " ", s)
    s = re.sub(r"^(my|the|a|an)\s+", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def token_f1(a: str, b: str) -> float:
    ta, tb = Counter(a.split()), Counter(b.split())
    common = sum((ta & tb).values())
    if common == 0:
        return 0.0
    p, r = common / sum(tb.values()), common / sum(ta.values())
    return 2 * p * r / (p + r)


def slot_match(name: str, gold: object, pred: object, lenient: bool) -> bool:
    g, p = norm(gold), norm(pred)
    if g is None or p is None:
        return g is None and p is None
    if g == p:
        return True
    if lenient and isinstance(g, str) and isinstance(p, str):
        if name in FREE_TEXT or name in ("recipient", "attendee", "when", "schedule"):
            return token_f1(g, p) >= 0.5
    return False


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def llm_route(client, model: str, text: str, sch: dict) -> dict:
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
    opts = {"temperature": 0, "num_ctx": 4096, "seed": 0}
    t0 = time.perf_counter()
    r = client.chat(model=model, messages=msgs, format=sch, think=False, options=opts, keep_alive="30m")
    lat = time.perf_counter() - t0
    raw = r.message.content
    obj, err = validate(raw)
    first_valid = obj is not None
    repaired = False
    if obj is None:
        msgs += [{"role": "assistant", "content": raw}, {"role": "user", "content": f"That was invalid ({err}). Reply with corrected JSON only."}]
        r = client.chat(model=model, messages=msgs, format=sch, think=False, options=opts, keep_alive="30m")
        obj, err = validate(r.message.content)
        repaired = obj is not None
    return {"obj": obj, "first_valid": first_valid, "repaired": repaired, "latency_s": lat}


def score(preds: list[dict]) -> dict:
    n = len(UTTERANCES)
    correct = sum(1 for u, p in zip(UTTERANCES, preds) if p["intent"] == u["intent"])
    strict_ok = strict_n = lenient_ok = 0
    confusion: Counter[str] = Counter()
    errors = []
    for u, p in zip(UTTERANCES, preds):
        if p["intent"] != u["intent"]:
            confusion[f"{u['intent']} -> {p['intent']}"] += 1
            errors.append({"id": u["id"], "text": u["text"], "gold": u["intent"], "pred": p["intent"]})
            continue
        for s in INTENT_SLOTS[u["intent"]]:
            strict_n += 1
            gold, pred = u["slots"].get(s), p["slots"].get(s)
            strict_ok += slot_match(s, gold, pred, lenient=False)
            ok = slot_match(s, gold, pred, lenient=True)
            lenient_ok += ok
            if not ok:
                errors.append({"id": u["id"], "slot": s, "gold": gold, "pred": pred})
    return {
        "n": n,
        "intent_correct": correct,
        "intent_accuracy": round(correct / n, 4),
        "intent_wilson95": wilson(correct, n),
        "slots_evaluated": strict_n,
        "slot_accuracy_strict": round(strict_ok / strict_n, 4) if strict_n else None,
        "slot_accuracy_lenient": round(lenient_ok / strict_n, 4) if strict_n else None,
        "confusions": dict(confusion.most_common()),
        "errors": errors,
    }


def grammar_stats() -> tuple[dict, list[tuple[str, dict] | None]]:
    out = [grammar_parse(u["text"]) for u in UTTERANCES]
    fired = [(u, g) for u, g in zip(UTTERANCES, out) if g is not None]
    right = [(u, g) for u, g in fired if g[0] == u["intent"]]
    wrong = [{"id": u["id"], "text": u["text"], "gold": u["intent"], "pred": g[0]} for u, g in fired if g[0] != u["intent"]]
    return {
        "coverage": round(len(fired) / len(UTTERANCES), 4),
        "fired": len(fired),
        "precision": round(len(right) / len(fired), 4) if fired else None,
        "wrong_fires": wrong,
    }, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen3:1.7b", "qwen3.5:4b", "qwen3:8b"])
    ap.add_argument("--grammar-only", action="store_true")
    args = ap.parse_args()

    gstats, gout = grammar_stats()
    print(f"grammar: coverage {gstats['coverage']}, precision {gstats['precision']}, wrong fires {len(gstats['wrong_fires'])}")
    for w in gstats["wrong_fires"]:
        print("  WRONG", w)
    if args.grammar_only:
        abstain = {"intent": None, "slots": {}}
        g_preds = [{"intent": g[0], "slots": g[1]} if g else abstain for g in gout]
        write_result("routing", "grammar", {"grammar": gstats, "score_if_abstain_is_wrong": score(g_preds)})
        return

    import ollama

    client = ollama.Client(host="http://127.0.0.1:11434")
    sch = schema()
    results: dict[str, dict] = {}
    for model in args.models:
        print(f"== {model}")
        client.chat(model=model, messages=[{"role": "user", "content": "hi"}], think=False, keep_alive="30m", options={"num_predict": 1})
        llm_preds, lat, first_valid, repaired = [], [], 0, 0
        for i, u in enumerate(UTTERANCES):
            r = llm_route(client, model, u["text"], sch)
            lat.append(r["latency_s"])
            first_valid += r["first_valid"]
            repaired += r["repaired"]
            obj = r["obj"] or {"intent": "INVALID", "slots": {}}
            llm_preds.append({"intent": obj["intent"], "slots": obj.get("slots", {})})
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(UTTERANCES)}  p50 {summarize(lat)['p50']}s")
        hybrid = [{"intent": g[0], "slots": g[1]} if g else p for g, p in zip(gout, llm_preds)]
        n = len(UTTERANCES)
        results[model] = {
            "llm": score(llm_preds),
            "hybrid": score(hybrid),
            "valid_json_first_try": round(first_valid / n, 4),
            "valid_json_after_repair": round((first_valid + repaired) / n, 4),
            "latency_s": summarize(lat),
        }
        client.generate(model=model, prompt="", keep_alive=0)
        print(
            f"  llm intent {results[model]['llm']['intent_accuracy']} hybrid {results[model]['hybrid']['intent_accuracy']} "
            f"json {results[model]['valid_json_first_try']} lat p50 {results[model]['latency_s']['p50']}s"
        )

    write_result("routing", "routing", {"grammar": gstats, "system_prompt": SYSTEM, "models": results, "method": __doc__})


if __name__ == "__main__":
    main()

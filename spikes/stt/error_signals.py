"""Which signals detect a misheard word? Parakeet p, top-2 margin, Whisper disagreement, Whisper forced score."""
import inspect, json, sys, time, wave
from pathlib import Path
import numpy as np
from swift.stt.improve import align, normalize

S = Path("//localhost/c$/Users/frchi/AppData/Local/Swift")
OUT = Path(sys.argv[1])
WHISPER = sys.argv[2] if len(sys.argv) > 2 else "base.en"

def read_wav(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0

def sets():
    out = []
    for name, folder in (("read", S / "stt_corpus"), ("noisy", S / "stt_noisy")):
        for line in (folder / "refs.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("ref"):
                    out.append((name if name == "read" else (r.get("condition") or "noisy"), folder / r["wav"], r["ref"]))
    kept = S / "stt_testset"
    for c in json.loads((kept / "index.json").read_text(encoding="utf-8")).get("clips", []):
        if c.get("known") and (kept / c["wav"]).exists():
            out.append(("kept", kept / c["wav"], c["known"]))
    return out

def lsm(x):
    x = x - x.max(); return x - np.log(np.exp(x).sum())

import onnx_asr, onnxruntime
opts = onnxruntime.SessionOptions(); opts.intra_op_num_threads = 4; opts.inter_op_num_threads = 1
model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", S / "models/parakeet-tdt-0.6b-v2", quantization="int8", sess_options=opts).with_timestamps()
asr = model
while not hasattr(asr, "_decode"):
    asr = asr.asr
calls = []
orig = asr._decode
def spy(prev, state, enc):
    logits, step, new = orig(prev, state, enc)
    l = lsm(np.asarray(logits, np.float64)); top = np.argsort(l)[-2:]
    calls.append((int(top[1]), float(l[top[1]]), float(l[top[0]])))
    return logits, step, new
asr._decode = spy
blank = asr._blank_idx

from faster_whisper import WhisperModel
from faster_whisper.tokenizer import Tokenizer
from faster_whisper.audio import pad_or_trim
wm = WhisperModel(WHISPER, device="cpu", compute_type="int8", cpu_threads=4, download_root=str(S / "models/whisper"), local_files_only=True)
tok = Tokenizer(wm.hf_tokenizer, wm.model.is_multilingual, task="transcribe", language="en")
print("find_alignment", inspect.signature(wm.find_alignment), flush=True)

def group(tokens):
    """[(word, [token indices])], as words_from_tokens groups them (punctuation joins, uncounted)."""
    import re
    punct = re.compile(r"^[\W_]*$"); words = []
    for i, t in enumerate(tokens):
        p = bool(punct.match(t.strip()))
        if t.startswith((" ", "▁")) and not p or not words:
            words.append([t.strip(" ▁"), [] if p else [i]])
        else:
            words[-1][0] += t
            if not p: words[-1][1].append(i)
    return [(w, ix) for w, ix in words if ix]

def norm_map(words):
    flat, back = [], []
    for i, w in enumerate(words):
        for n in normalize(w):
            flat.append(n); back.append(i)
    return flat, back

rows, timing = [], {"parakeet": [], "w_encode_score": [], "w_transcribe": [], "audio_s": []}
clips = sets()
for k, (set_, path, ref) in enumerate(clips):
    a = read_wav(path); calls.clear()
    t0 = time.perf_counter(); res = model.recognize(a, sample_rate=16000); timing["parakeet"].append(time.perf_counter() - t0)
    emitted = [c for c in calls if c[0] != blank]
    toks, lps = res.tokens or [], res.logprobs or []
    ok_margin = len(emitted) == len(toks)
    words = group(toks)
    if not words: continue
    texts = [w for w, _ in words]
    hyp, hback = norm_map(texts); refn = normalize(ref)
    wrong = set()
    for op, r0, r1, h0, h1 in align(refn, hyp):
        if op in ("sub", "ins"): wrong.add(hback[h0])
    dels = sum(op == "del" for op, *_ in align(refn, hyp))
    # Whisper: forced score of Parakeet's text, then its own transcript
    t0 = time.perf_counter()
    feats = wm.feature_extractor(a); nfr = feats.shape[-1]
    enc = wm.encode(pad_or_trim(feats))
    ptext = " " + res.text.strip()
    al = wm.find_alignment(tok, [tok.encode(ptext)], enc, nfr)[0]
    timing["w_encode_score"].append(time.perf_counter() - t0)
    wwords = [(d["word"], float(d["probability"])) for d in al] if al and isinstance(al[0], dict) else [(d.word, float(d.probability)) for d in al]
    wflat, wback = norm_map([w for w, _ in wwords])
    forced = {}
    for op, r0, r1, h0, h1 in align(hyp, wflat):
        if op == "equal":
            i = hback[r0]; forced[i] = min(forced.get(i, 1.0), wwords[wback[h0]][1])
    t0 = time.perf_counter()
    segs, _ = wm.transcribe(a, language="en", beam_size=5, vad_filter=False, temperature=0.0, condition_on_previous_text=False)
    wtext = " ".join(s.text.strip() for s in segs); timing["w_transcribe"].append(time.perf_counter() - t0)
    timing["audio_s"].append(len(a) / 16000)
    wh = normalize(wtext); agree = set()
    for op, r0, r1, h0, h1 in align(hyp, wh):
        if op == "equal": agree.add(hback[r0])
    w_right = int(wh == refn)
    for i, (w, ix) in enumerate(words):
        if i not in set(hback): continue  # fillers, punctuation
        rows.append({"set": set_, "clip": k, "i": i, "word": w if set_ != "kept" else "", "wrong": int(i in wrong),
                     "p": float(np.exp(min(lps[j] for j in ix))),
                     "margin": float(min(emitted[j][1] - emitted[j][2] for j in ix)) if ok_margin else None,
                     "disagree": int(i not in agree), "forced": forced.get(i),
                     "dels": dels, "w_right": w_right, "p_right": int(hyp == refn)})
    if k % 10 == 0: print(k, len(clips), flush=True)
OUT.write_text(json.dumps({"rows": rows, "timing": timing, "whisper": WHISPER}), encoding="utf-8")
print("done", len(rows))

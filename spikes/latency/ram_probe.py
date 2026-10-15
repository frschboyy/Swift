"""S2: resident memory per component, each measured in a fresh subprocess.

Usage:  uv run --group spikes python spikes/latency/ram_probe.py

Components: bare interpreter, numpy+onnxruntime, Silero VAD (ONNX bundled
with faster-whisper), whisper base.en / small.en (int8), Piper voice.
For each: private MiB after imports, after load, and after one inference.
Ollama model RAM is measured by llm_bench.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _util import SPIKES_DIR, models_dir, write_result  # noqa: E402

CHILD = r"""
import json, sys, psutil
sys.path.insert(0, {spikes!r})
from _util import private_mb
comp = {comp!r}
r = {{"start": private_mb()}}
import numpy as np
audio = np.zeros(16000 * 5, dtype=np.float32)
if comp == "baseline":
    pass
elif comp == "onnxruntime":
    import onnxruntime
    r["imports"] = private_mb()
elif comp == "silero_vad":
    import onnxruntime, faster_whisper, pathlib
    r["imports"] = private_mb()
    assets = pathlib.Path(faster_whisper.__file__).parent / "assets"
    model = sorted(assets.glob("silero*.onnx"))[-1]
    sess = onnxruntime.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    r["model"] = model.name
    r["inputs"] = [(i.name, i.shape, i.type) for i in sess.get_inputs()]
    r["loaded"] = private_mb()
elif comp.startswith("whisper-"):
    from faster_whisper import WhisperModel
    r["imports"] = private_mb()
    m = WhisperModel(comp.split("-", 1)[1], device="cpu", compute_type="int8", download_root={whisper_root!r})
    r["loaded"] = private_mb()
    list(m.transcribe(audio, language="en", beam_size=1)[0])
    r["after_inference"] = private_mb()
elif comp == "piper":
    from piper import PiperVoice
    r["imports"] = private_mb()
    v = PiperVoice.load({piper_model!r})
    r["loaded"] = private_mb()
    for _ in v.synthesize("This is a memory probe sentence."):
        pass
    r["after_inference"] = private_mb()
r["peak_wset_mb"] = round(psutil.Process().memory_info().peak_wset / 2**20, 1)
print(json.dumps(r))
"""

COMPONENTS = ["baseline", "onnxruntime", "silero_vad", "whisper-base.en", "whisper-small.en", "piper"]


def main() -> None:
    piper_model = models_dir() / "piper" / "en_US-lessac-medium" / "en_US-lessac-medium.onnx"
    out = {}
    for comp in COMPONENTS:
        code = CHILD.format(
            spikes=str(SPIKES_DIR), comp=comp, whisper_root=str(models_dir() / "whisper"), piper_model=str(piper_model)
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            out[comp] = {"error": proc.stderr.strip().splitlines()[-1:]}
        else:
            out[comp] = json.loads(proc.stdout.strip().splitlines()[-1])
        print(comp, out[comp])
    write_result("latency", "ram", {"components": out, "method": "fresh subprocess per component; private bytes"})


if __name__ == "__main__":
    main()

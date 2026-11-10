"""Run ViolaWake's trainer (0.2.10) with nothing sent off the PC: same arguments, its quality gate skipped.

With --no-auto-corpus the trainer uses only the clips it's given, but its post-training quality gate still
makes check phrases with Edge TTS (an online service), and it exports no model if the gate fails. The
gate is skipped here; wake_bench.py scores the model on the owner's own clips instead.

  python viola_train_offline.py --word "hey swift" --positives DIR --negatives DIR --no-auto-corpus --output M.onnx
"""

import sys

import violawake_sdk.tools.train as train


def no_gate(*args, **kwargs):
    print("  quality gate skipped (it needs online TTS); scored on the owner's clips by wake_bench.py")
    return "skipped", {"d_prime": None, "speech_fp_rate": None, "confusable_fp_rate": None}


def no_online_tts(text, voice, output_path, *args, **kwargs):
    raise RuntimeError("online TTS is off in this spike")


if __name__ == "__main__":
    train._run_quality_gate = no_gate
    train._edge_tts_synthesize = no_online_tts
    sys.argv[0] = "violawake-train"
    train.main()

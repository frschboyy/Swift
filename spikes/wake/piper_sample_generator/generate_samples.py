"""openWakeWord's train.py imports `generate_samples` from `piper_sample_generator_path`: point it at this folder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from piper_samples import generate_samples  # noqa: E402, F401

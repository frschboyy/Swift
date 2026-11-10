"""Run openWakeWord's train.py (0.6.0) on Windows: same arguments, one Linux-only step replaced.

openwakeword.utils.compute_features_from_generator trims its output file (openwakeword.data.trim_mmap) while
the file is still memory-mapped, which Windows refuses (WinError 32 / Errno 22). Here the trim is skipped
inside that function and done after it returns, when its map is gone: read the kept rows, rewrite the file.

  python oww_train_windows.py --training_config hey_swift.yaml --augment_clips --train_model
"""

import gc
import runpy
import sys

import numpy as np
import openwakeword.data
import openwakeword.utils


def trim_mmap(mmap_path: str) -> None:
    rows = np.load(mmap_path, mmap_mode="r")
    last = -1
    while np.all(rows[last] == 0):
        last -= 1
    kept = np.array(rows[: rows.shape[0] + last + 1], dtype=np.float32)
    del rows
    gc.collect()
    np.save(mmap_path, kept)


_compute = openwakeword.utils.compute_features_from_generator


def compute_features_from_generator(*args, **kwargs):
    _compute(*args, **kwargs)
    gc.collect()  # drop its map of the file first
    trim_mmap(kwargs.get("output_file", args[3] if len(args) > 3 else None))


if __name__ == "__main__":
    openwakeword.data.trim_mmap = lambda path: None  # utils imports it from data at call time
    openwakeword.utils.compute_features_from_generator = compute_features_from_generator  # train.py imports it
    sys.argv[0] = "openwakeword.train"
    runpy.run_module("openwakeword.train", run_name="__main__", alter_sys=True)

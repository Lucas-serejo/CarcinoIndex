"""Run Experiment A: offline ENID segmentation with official reference boxes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ai.segmentation.sam_segmenter import DEFAULT_MODEL_CONFIG  # noqa: E402
from experiments.benchmarks.enid.runner import run_benchmark  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("all", "train", "val", "test"), default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", choices=("float32", "bfloat16"), default="float32")
    parser.add_argument("--config", dest="model_config", default=DEFAULT_MODEL_CONFIG)
    args = parser.parse_args(argv)
    try:
        summary = run_benchmark(**vars(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"ENID complete: {summary['annotations_processed']} annotations, "
          f"{summary['images_processed']} images. Outputs: results.csv, summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

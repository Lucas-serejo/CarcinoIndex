"""Render every unique quantitatively selected ENID annotation for inspection."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.analysis.enid.qualitative import DEFAULT_MODEL_CONFIG, render_cases  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset-root", "split-root", "results", "cases", "checkpoint", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", choices=("float32", "bfloat16"), default="float32")
    parser.add_argument("--model-config", default=DEFAULT_MODEL_CONFIG)
    args = parser.parse_args(argv)
    try:
        manifest = render_cases(**vars(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Rendered {manifest['unique_annotations_rendered']} unique annotations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

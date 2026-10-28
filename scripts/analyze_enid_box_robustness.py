"""Analyze a completed ENID box-robustness run on CPU without loading SAM or images."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.analysis.enid.robustness_analysis import analyze_robustness  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="results_long.csv")
    parser.add_argument("--timing", type=Path, default=None,
                        help="image_timing.csv (default: next to --results)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "pt-BR"), default="en")
    parser.add_argument("--expected-sha256", default=None,
                        help="Abort before writing if results_long.csv has a different SHA-256.")
    args = parser.parse_args(argv)
    try:
        summary = analyze_robustness(**vars(args))
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"ENID robustness analysis complete: {summary['annotation_count']} annotations x "
          f"{len(summary['by_condition'])} conditions; outputs: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

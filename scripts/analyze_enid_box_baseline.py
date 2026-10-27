"""Compare ENID SAM results with the filled reference bbox on CPU, without SAM or images."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.analysis.enid.box_baseline import analyze_box_baseline  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-root", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "pt-BR"), default="en")
    parser.add_argument("--expected-sha256", default=None,
                        help="Abort before writing if results.csv has a different SHA-256.")
    args = parser.parse_args(argv)
    try:
        summary = analyze_box_baseline(**vars(args))
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"ENID box baseline complete: {summary['row_count']} annotations; outputs: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

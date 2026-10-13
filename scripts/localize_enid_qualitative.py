"""Render existing ENID qualitative artifacts read-only, without SAM inference."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.analysis.enid.render_only import render_existing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset-root", "split-root", "results", "cases", "source", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "pt-BR"), default="pt-BR")
    args = parser.parse_args(argv)
    try:
        manifest = render_existing(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Render-only: {manifest['unique_annotations_rendered']} verified annotations; {args.language}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Export finalized Experiment B evaluations to CSV (read-only; no SAM, CUDA, images, or masks)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
for _path in (SCRIPTS_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from _local_env import load_local_env  # noqa: E402
from backend.app.persistence.database import PersistenceSettings, create_database_engine  # noqa: E402
from backend.app.persistence.experiment_b_export import export_experiment_b, format_summary  # noqa: E402

ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / "experiments" / "outputs" / "experiment_b" / "evaluations.csv"


def _display(path: Path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:  # Different drive on Windows.
        return str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="CSV path (default: experiments/outputs/experiment_b/evaluations.csv)")
    args = parser.parse_args(argv)
    try:
        load_local_env(ENV_FILE)  # Process variables win over .env values.
        engine = create_database_engine(PersistenceSettings.from_env())
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        rows = export_experiment_b(engine, args.output)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(f"ERROR: database read failed: {getattr(exc, 'orig', None) or type(exc).__name__}",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: could not write CSV: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(format_summary(rows, _display(args.output.resolve())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reset local CarcinoIndex experiment data (dry run unless --execute --confirm <database>).

No SAM, CUDA, or image decoding is required. There is no automatic backup.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.app.persistence.database import PersistenceSettings, create_database_engine  # noqa: E402
from backend.app.persistence.experiment_reset import (  # noqa: E402
    OrphanedFiles, ResetAborted, format_report, format_snapshot, reset_experiment_data, snapshot,
)


def _display(path: Path) -> str:
    """Relative inside the current directory; absolute otherwise, so the target is unambiguous."""
    return os.path.relpath(path) if path.is_relative_to(Path.cwd()) else str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Actually delete data (requires --confirm).")
    parser.add_argument("--confirm", metavar="DATABASE", help="Exact database name from DATABASE_URL.")
    args = parser.parse_args(argv)
    try:
        settings = PersistenceSettings.from_env()
        engine = create_database_engine(settings)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    database_name = make_url(settings.database_url).database or ""
    storage_label = _display(settings.storage_root)
    try:
        if not args.execute:
            print("Experiment data reset - DRY RUN\n")
            print(format_snapshot(snapshot(engine, settings.storage_root), database_name, storage_label))
            print(f"\nNo changes were made. To reset, run with: --execute --confirm {database_name}")
            return 0
        report = reset_experiment_data(engine, settings.storage_root,
                                       database_name=database_name, confirm=args.confirm)
    except ResetAborted as exc:
        print(f"ABORTED: {exc} No changes were made.", file=sys.stderr)
        return 2
    except OrphanedFiles as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print("ERROR: database operation failed; any open transaction was rolled back and no "
              f"storage file was changed: {getattr(exc, 'orig', None) or type(exc).__name__}",
              file=sys.stderr)
        return 1
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(format_report(report, database_name, storage_label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reset local experiment data: the four experiment tables and LocalStorage-managed files.

Schema, alembic_version, and any storage file outside the LocalStorage key
contract are preserved. Intended for local/development databases only.
"""

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.storage.local import is_managed_key

TABLES = ("clinical_cases", "images", "evaluations", "segmentation_attempts")
CATEGORIES = ("images", "masks")
TRUNCATE_SQL = "TRUNCATE segmentation_attempts, evaluations, images, clinical_cases"
HEALTH_URL = "http://127.0.0.1:8000/health"


class ResetAborted(RuntimeError):
    """Nothing was changed."""


class OrphanedFiles(RuntimeError):
    """The database was reset, but some managed files remain on disk."""


@dataclass(frozen=True)
class Snapshot:
    tables: dict[str, int]
    files: dict[str, int]
    alembic_revision: str | None


@dataclass(frozen=True)
class ResetReport:
    before: Snapshot
    after: Snapshot


def backend_is_running(url: str = HEALTH_URL, timeout: float = 5.0) -> bool:
    """Only a refused connection proves that no API is listening.

    Any HTTP answer (200 or 503) or a timeout means a server accepted the
    connection, so the reset must not proceed. Windows needs ~2 s to refuse a
    closed localhost port, hence the longer timeout.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except urllib.error.URLError as exc:
        return not isinstance(exc.reason, ConnectionRefusedError)
    except ConnectionRefusedError:
        return False
    except OSError:
        return True


def managed_files(storage_root: Path) -> dict[str, list[Path]]:
    """Regular files directly in images/ or masks/ that match the LocalStorage key contract.

    Symlinks, subdirectories, unknown names, and category folders that resolve
    outside STORAGE_ROOT are never included.
    """
    root = storage_root.resolve()
    found: dict[str, list[Path]] = {}
    for category in CATEGORIES:
        folder = root / category
        found[category] = []
        if not folder.is_dir() or folder.resolve() != folder:
            continue
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and is_managed_key(f"{category}/{entry.name}"):
                    found[category].append(Path(entry.path))
    return found


def snapshot(engine: Engine, storage_root: Path) -> Snapshot:
    with engine.connect() as connection:
        tables = {name: connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()
                  for name in TABLES}
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    files = {category: len(paths) for category, paths in managed_files(storage_root).items()}
    return Snapshot(tables, files, revision)


def reset_experiment_data(engine: Engine, storage_root: Path, *, database_name: str,
                          confirm: str | None, backend_check=None) -> ResetReport:
    if confirm != database_name:
        raise ResetAborted("--confirm must exactly match the database name shown in the dry run.")
    if (backend_check or backend_is_running)():
        raise ResetAborted("Stop the CarcinoIndex backend before resetting experiment data.")
    before = snapshot(engine, storage_root)
    with engine.begin() as connection:  # Any failure rolls back; storage is untouched.
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text(TRUNCATE_SQL))
    database_after = snapshot(engine, storage_root)
    if any(database_after.tables.values()) or database_after.alembic_revision != before.alembic_revision:
        raise RuntimeError("Database reset could not be verified; storage was not changed.")
    failed = 0
    for paths in managed_files(storage_root).values():
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                failed += 1
    after = snapshot(engine, storage_root)
    if failed or any(after.files.values()):
        remaining = ", ".join(f"{category}: {count}" for category, count in after.files.items())
        raise OrphanedFiles(
            "The database was reset, but some managed storage files could not be removed "
            f"({remaining}). They are now orphaned files. Fix the cause (for example, a file "
            "locked by another program or by OneDrive) and run the command again.")
    return ResetReport(before, after)


def format_snapshot(snapshot: Snapshot, database_name: str, storage_label: str) -> str:
    return "\n".join([
        f"Database ({database_name}):",
        *(f"  {name}: {snapshot.tables[name]}" for name in TABLES),
        "",
        f"Storage ({storage_label}):",
        *(f"  managed {category}: {snapshot.files[category]}" for category in CATEGORIES),
    ])


def format_report(report: ResetReport, database_name: str, storage_label: str) -> str:
    before, after = report.before, report.after
    return "\n".join([
        "Experiment data reset completed",
        "",
        f"Database ({database_name}):",
        *(f"  {name}: {before.tables[name]} -> {after.tables[name]}" for name in TABLES),
        "",
        f"Storage ({storage_label}):",
        *(f"  managed {category}: {before.files[category]} -> {after.files[category]}"
          for category in CATEGORIES),
        "",
        f"Schema and Alembic migration state were preserved (revision {after.alembic_revision}).",
    ])

"""Local experiment data reset; database tests use a random PostgreSQL schema."""

import importlib.util
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.persistence import experiment_reset
from backend.app.persistence.database import create_session_factory
from backend.app.persistence.experiment_reset import (
    OrphanedFiles, ResetAborted, backend_is_running, reset_experiment_data, snapshot,
)
from backend.app.persistence.repository import ExperimentRepository

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reset_experiment_data.py"
postgresql = pytest.mark.postgresql
DB = "carcinoindex_test"


def seed(engine):
    with create_session_factory(engine).begin() as session:
        repo = ExperimentRepository(session)
        case = repo.create_case("CASE-001")
        image = repo.add_image(case_id=case.id, storage_path=f"images/{uuid4().hex}.jpg",
                               width=32, height=24, sha256="c" * 64)
        evaluation = repo.create_evaluation(image_id=image.id, pci_region_id=1, annotator_code="expert")
        for _ in range(2):
            repo.add_attempt(evaluation_id=evaluation.id, prompt_type="box", prompt_data={"box_xyxy": [1, 1, 9, 9]},
                             mask_storage_path=f"masks/{uuid4().hex}.png", sam_metadata={"selected_score": 0.9})


def storage(tmp_path):
    """Managed files plus files that must survive any reset."""
    root = tmp_path / "storage"
    managed = [root / "images" / f"{uuid4().hex}.jpg", root / "masks" / f"{uuid4().hex}.png",
               root / "masks" / f"{uuid4().hex}.png"]
    kept = [root / "images" / "manual-notes.png", root / "images" / f"{uuid4().hex.upper()}.png",
            root / "images" / f"{uuid4().hex}.gif", root / "images" / "sub" / f"{uuid4().hex}.png",
            root / "masks" / f"{uuid4().hex}.png.bak", root / "other" / f"{uuid4().hex}.png",
            root / f"{uuid4().hex}.png"]
    for path in managed + kept:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic")
    return root, managed, kept


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def alembic_revision(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def reset(engine, root, confirm=DB, running=False):
    return reset_experiment_data(engine, root, database_name=DB, confirm=confirm,
                                 backend_check=lambda: running)


def load_script():
    spec = importlib.util.spec_from_file_location("reset_experiment_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ENV_FILE = SCRIPT.with_name("no-such.env")  # Never read the developer's .env.
    return module


@postgresql
def test_dry_run_reports_counts_and_changes_nothing(database, tmp_path, monkeypatch, capsys):
    engine = database[0]
    seed(engine)
    root, _, _ = storage(tmp_path)
    before_files, before = files(root), snapshot(engine, root)
    script = load_script()
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://user:SECRET-PW@127.0.0.1/{DB}")
    monkeypatch.setenv("STORAGE_ROOT", str(root))
    monkeypatch.setattr(script, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(experiment_reset, "backend_is_running", lambda: pytest.fail("dry run must not probe"))
    assert script.main([]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "No changes were made." in out
    for line in ("clinical_cases: 1", "images: 1", "evaluations: 1", "segmentation_attempts: 2",
                 "managed images: 1", "managed masks: 2"):
        assert line in out
    assert "SECRET-PW" not in out and "CASE-001" not in out and "expert" not in out
    assert snapshot(engine, root) == before and files(root) == before_files


@postgresql
@pytest.mark.parametrize("confirm,running", [(None, False), ("carcinoindex", False), (DB.upper(), False), (DB, True)])
def test_wrong_confirmation_or_active_backend_aborts_without_changes(database, tmp_path, confirm, running):
    engine = database[0]
    seed(engine)
    root, _, _ = storage(tmp_path)
    before_files, before = files(root), snapshot(engine, root)
    with pytest.raises(ResetAborted, match="Stop the CarcinoIndex backend" if running else "--confirm"):
        reset(engine, root, confirm=confirm, running=running)
    assert snapshot(engine, root) == before and files(root) == before_files


@postgresql
def test_reset_clears_tables_and_managed_files_only(database, tmp_path):
    engine = database[0]
    seed(engine)
    root, managed, kept = storage(tmp_path)
    revision = alembic_revision(engine)
    report = reset(engine, root)
    assert report.before.tables == {"clinical_cases": 1, "images": 1, "evaluations": 1, "segmentation_attempts": 2}
    assert report.before.files == {"images": 1, "masks": 2}
    assert set(report.after.tables.values()) == {0} and report.after.files == {"images": 0, "masks": 0}
    assert alembic_revision(engine) == revision == report.after.alembic_revision
    assert not any(path.exists() for path in managed)
    assert all(path.exists() for path in kept)
    with create_session_factory(engine).begin() as session:  # Schema still usable.
        ExperimentRepository(session).create_case("after-reset")


@postgresql
def test_reset_is_idempotent_when_already_empty(database, tmp_path):
    engine = database[0]
    root = tmp_path / "missing-storage"
    for _ in range(2):
        report = reset(engine, root)
        assert set(report.before.tables.values()) == set(report.after.tables.values()) == {0}
        assert report.after.files == {"images": 0, "masks": 0}


@postgresql
def test_truncate_failure_rolls_back_and_leaves_storage(database, tmp_path, monkeypatch):
    engine = database[0]
    seed(engine)
    root, _, _ = storage(tmp_path)
    before_files, before = files(root), snapshot(engine, root)
    # Without CASCADE, truncating only images violates evaluations' foreign key.
    monkeypatch.setattr(experiment_reset, "TRUNCATE_SQL", "TRUNCATE images")
    with pytest.raises(Exception, match="foreign key"):
        reset(engine, root)
    assert snapshot(engine, root) == before and files(root) == before_files


@postgresql
def test_undeletable_managed_file_is_reported_as_orphan(database, tmp_path, monkeypatch):
    engine = database[0]
    seed(engine)
    root, managed, _ = storage(tmp_path)
    original = Path.unlink
    def unlink(self, *args, **kwargs):
        if self.name == managed[0].name:
            raise PermissionError("locked")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(OrphanedFiles, match="images: 1, masks: 0.*run the command again"):
        reset(engine, root)
    assert set(snapshot(engine, root).tables.values()) == {0}
    monkeypatch.setattr(Path, "unlink", original)
    assert reset(engine, root).after.files == {"images": 0, "masks": 0}


def test_symlinks_are_never_followed(tmp_path):
    root, outside = tmp_path / "storage", tmp_path / "outside"
    (root / "images").mkdir(parents=True)
    outside.mkdir()
    target = outside / "keep.png"
    target.write_bytes(b"keep")
    try:
        os.symlink(target, root / "images" / f"{uuid4().hex}.png")
        os.symlink(outside, root / "masks", target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is not permitted here.")
    (outside / f"{uuid4().hex}.png").write_bytes(b"keep")
    assert experiment_reset.managed_files(root) == {"images": [], "masks": []}


def test_backend_probe_distinguishes_listening_server_from_refused_port():
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert backend_is_running(f"http://127.0.0.1:{server.server_port}/health")
    finally:
        server.shutdown()
        server.server_close()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
    assert not backend_is_running(f"http://127.0.0.1:{free_port}/health")


@pytest.mark.parametrize("url", [None, "postgresql://user:SECRET-PW@127.0.0.1/db",
                                 "postgresql+psycopg://user:SECRET-PW@127.0.0.1:1/db?connect_timeout=3"])
def test_database_url_errors_are_safe(monkeypatch, capsys, url):
    if url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", url)
    assert load_script().main([]) == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "SECRET-PW" not in captured.out + captured.err

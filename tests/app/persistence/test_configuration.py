from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from backend.app.persistence.database import PersistenceSettings


def test_persistence_requires_explicit_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        PersistenceSettings.from_env()


@pytest.mark.parametrize("url", ["sqlite://", "postgresql://localhost/db"])
def test_only_postgresql_psycopg(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="postgresql\\+psycopg"):
        PersistenceSettings.from_env()


def test_environment_and_secret_repr(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:secret@localhost/db")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    settings = PersistenceSettings.from_env()
    assert settings.storage_root == tmp_path.resolve()
    assert settings.database_url not in repr(settings)
    assert "user:secret" not in repr(settings)


def test_migration_renders_postgresql_without_connection(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/unused")
    output = StringIO()
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    for table in ("clinical_cases", "images", "evaluations", "segmentation_attempts"):
        assert f"CREATE TABLE {table}" in sql
    assert "JSONB" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "uq_attempt_evaluation_sequence" in sql
    assert "status != 'finalized' OR clinical_ls IS NOT NULL" in sql
    assert "clinical_ls BETWEEN 0 AND 3" in sql
    assert "annotator_confidence" in sql
    assert "original_filename" not in sql
    output.truncate(0)
    output.seek(0)
    command.downgrade(config, "0001_experiment:base", sql=True)
    assert "DROP TABLE clinical_cases" in output.getvalue()

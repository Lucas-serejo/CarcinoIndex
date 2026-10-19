"""Local CLI .env loading; no database access."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _local_env import load_local_env  # noqa: E402

from backend.app.persistence.experiment_reset import Snapshot  # noqa: E402

KEYS = ("DATABASE_URL", "STORAGE_ROOT", "QUOTED_DOUBLE", "QUOTED_SINGLE", "WITH_EQUALS",
        "SAM2_CHECKPOINT_PATH", "EMPTY_VALUE")


@pytest.fixture(autouse=True)
def isolated_environ():
    saved = dict(os.environ)
    for key in KEYS:
        os.environ.pop(key, None)
    yield
    os.environ.clear()
    os.environ.update(saved)


def write_env(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    return path


def load_script(name, env_file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ENV_FILE = env_file
    return module


def test_parses_project_format_without_overriding_process(tmp_path):
    os.environ["STORAGE_ROOT"] = "from-process"
    path = write_env(tmp_path, "\n".join([
        "# Docker Compose reads .env",
        "",
        "  DATABASE_URL = postgresql+psycopg://user:p%40ss@127.0.0.1:5432/carcinoindex?sslmode=disable  ",
        "STORAGE_ROOT=./storage",
        'QUOTED_DOUBLE="value with spaces"',
        "QUOTED_SINGLE='single'",
        "WITH_EQUALS=a=b==c",
        r"SAM2_CHECKPOINT_PATH=C:\path\to\checkpoint.pt",
        "EMPTY_VALUE=",
        "   # indented comment",
    ]))
    assert set(load_local_env(path)) == set(KEYS) - {"STORAGE_ROOT"}
    assert os.environ["DATABASE_URL"] == "postgresql+psycopg://user:p%40ss@127.0.0.1:5432/carcinoindex?sslmode=disable"
    assert os.environ["STORAGE_ROOT"] == "from-process"
    assert os.environ["QUOTED_DOUBLE"] == "value with spaces"
    assert os.environ["QUOTED_SINGLE"] == "single"
    assert os.environ["WITH_EQUALS"] == "a=b==c"
    assert os.environ["SAM2_CHECKPOINT_PATH"] == r"C:\path\to\checkpoint.pt"
    assert os.environ["EMPTY_VALUE"] == ""


def test_missing_file_is_a_no_op(tmp_path):
    before = dict(os.environ)
    assert load_local_env(tmp_path / ".env") == []
    assert dict(os.environ) == before


@pytest.mark.parametrize("line", ["export DATABASE_URL=SECRET-VALUE", "1BAD=SECRET-VALUE", "SECRET-VALUE",
                                  "BAD-NAME=SECRET-VALUE", "=SECRET-VALUE"])
def test_invalid_line_fails_safely_and_loads_nothing(tmp_path, line):
    path = write_env(tmp_path, f"DATABASE_URL=first\n{line}\n")
    with pytest.raises(ValueError) as error:
        load_local_env(path)
    assert "line 2" in str(error.value) and "SECRET" not in str(error.value)
    assert "DATABASE_URL" not in os.environ


class _Engine:
    def dispose(self):
        pass


def test_export_script_reads_configuration_from_env_file(tmp_path, monkeypatch, capsys):
    env = write_env(tmp_path, f"DATABASE_URL=postgresql+psycopg://u:SECRET@127.0.0.1/from_env\n"
                              f"STORAGE_ROOT={tmp_path / 'store'}\n")
    script = load_script("export_experiment_b", env)
    seen = []
    monkeypatch.setattr(script, "create_database_engine", lambda settings: seen.append(settings) or _Engine())
    monkeypatch.setattr(script, "export_experiment_b", lambda engine, output: [])
    assert script.main(["--output", str(tmp_path / "out.csv")]) == 0
    assert seen[0].database_url.endswith("/from_env")
    assert seen[0].storage_root == (tmp_path / "store").resolve()
    assert "SECRET" not in capsys.readouterr().out


@pytest.mark.parametrize("process_url,expected", [(None, "from_env"),
                                                  ("postgresql+psycopg://u@127.0.0.1/from_shell", "from_shell")])
def test_reset_script_reads_env_file_and_process_wins(tmp_path, monkeypatch, capsys, process_url, expected):
    if process_url:
        os.environ["DATABASE_URL"] = process_url
    env = write_env(tmp_path, f"DATABASE_URL=postgresql+psycopg://u:SECRET@127.0.0.1/from_env\n"
                              f"STORAGE_ROOT={tmp_path / 'store'}\n")
    script = load_script("reset_experiment_data", env)
    zero = Snapshot({t: 0 for t in ("clinical_cases", "images", "evaluations", "segmentation_attempts")},
                    {"images": 0, "masks": 0}, "head")
    monkeypatch.setattr(script, "create_database_engine", lambda settings: _Engine())
    monkeypatch.setattr(script, "snapshot", lambda engine, root: zero)
    assert script.main([]) == 0
    out = capsys.readouterr().out
    assert f"Database ({expected}):" in out and "SECRET" not in out

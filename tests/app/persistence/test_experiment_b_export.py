"""Experiment B CSV export against real PostgreSQL; each test owns a random schema."""

import csv
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text, update

from backend.app.persistence.database import create_session_factory
from backend.app.persistence.experiment_b_export import (
    COLUMNS, InconsistentEvaluation, export_experiment_b, format_summary, read_rows,
)
from backend.app.persistence.models import Evaluation
from backend.app.persistence.repository import ExperimentRepository

pytestmark = pytest.mark.postgresql

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "export_experiment_b.py"


def metadata(score, pixels):
    return {"model_name": "sam2.1_hiera_small", "model_config": "configs/sam2.1/sam2.1_hiera_s.yaml",
            "checkpoint_name": "sam2.1_hiera_small.pt", "device": "cuda", "selected_index": 1,
            "selected_score": score, "mask_area_pixels": pixels, "mask_area_ratio": pixels / 768,
            "prediction_time_seconds": 0.25}


def create(session, *, code="case-001", attempts=1, reviewed=1, region=3, ls=2,
           confidence=0.8, quality="adequate", finalize=True):
    repo = ExperimentRepository(session)
    case = repo.create_case(code)
    image = repo.add_image(case_id=case.id, storage_path=f"images/SECRET-{uuid4().hex}.png",
                           width=32, height=24, sha256="b" * 64)
    evaluation = repo.create_evaluation(image_id=image.id, pci_region_id=region,
                                        annotator_code="expert-001")
    saved = [repo.add_attempt(evaluation_id=evaluation.id, prompt_type="box",
                              prompt_data={"multimask_output": True, "box_xyxy": [1, 2, 10 + n, 20]},
                              mask_storage_path=f"masks/SECRET-{uuid4().hex}.png",
                              sam_metadata=metadata(0.5 + n / 10, 100 + n))
             for n in range(1, attempts + 1)]
    if finalize:
        repo.finalize_evaluation(evaluation.id, clinical_ls=ls, annotator_confidence=confidence,
                                 reviewed_attempt_id=saved[reviewed - 1].id, segmentation_quality=quality)
    return evaluation, saved


def export(database, tmp_path):
    output = tmp_path / "nested" / "evaluations.csv"
    rows = export_experiment_b(database[0], output)
    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames) == COLUMNS
        return rows, list(reader), output.read_text(encoding="utf-8")


def snapshot(engine):
    with engine.connect() as connection:
        return {table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
                for table in ("clinical_cases", "images", "evaluations", "segmentation_attempts")}


def test_no_finalized_evaluations_writes_header_only(database, tmp_path):
    with create_session_factory(database[0]).begin() as session:
        create(session, finalize=False)  # Drafts are excluded.
    rows, records, content = export(database, tmp_path)
    assert rows == [] and records == []
    assert content.strip() == ",".join(COLUMNS)
    assert format_summary(rows, "out.csv").startswith("Exported 0 finalized evaluations")


def test_single_finalized_evaluation(database, tmp_path):
    with create_session_factory(database[0]).begin() as session:
        evaluation, (attempt,) = create(session, code="CASE-B-07", quality="partially_adequate")
        image = evaluation.image
    _, (row,), _ = export(database, tmp_path)
    assert row["evaluation_id"] == str(evaluation.id)
    assert row["case_id"] == str(image.case_id) and row["case_code"] == "CASE-B-07"
    assert (row["image_id"], row["image_sha256"]) == (str(image.id), "b" * 64)
    assert (row["image_width"], row["image_height"]) == ("32", "24")
    assert row["annotator_code"] == "expert-001" and row["pci_region_id"] == "3"
    assert row["segmentation_quality"] == "partially_adequate"
    assert (row["clinical_ls"], row["annotator_confidence"]) == ("2", "0.8")
    assert row["reviewed_attempt_id"] == str(attempt.id)
    assert (row["reviewed_attempt_sequence"], row["attempt_count"]) == ("1", "1")
    assert row["prompt_type"] == "box"
    assert row["prompt_data_json"] == '{"box_xyxy":[1,2,11,20],"multimask_output":true}'
    assert (row["model_name"], row["checkpoint_name"]) == ("sam2.1_hiera_small", "sam2.1_hiera_small.pt")
    assert row["model_config"] == "configs/sam2.1/sam2.1_hiera_s.yaml"
    assert (row["selected_index"], row["selected_score"], row["mask_area_pixels"]) == ("1", "0.6", "101")
    assert float(row["mask_area_ratio"]) == pytest.approx(101 / 768)
    assert row["prediction_time_seconds"] == "0.25"
    for column in ("evaluation_created_at", "finalized_at"):
        assert datetime.fromisoformat(row[column]).utcoffset() == timedelta(0)


def test_undetermined_region_and_ls_are_empty_cells(database, tmp_path):
    with create_session_factory(database[0]).begin() as session:
        create(session, region=None, ls=None, confidence=None)
    rows, (row,), content = export(database, tmp_path)
    assert row["pci_region_id"] == row["clinical_ls"] == row["annotator_confidence"] == ""
    assert "null" not in content.lower() and "None" not in content
    summary = format_summary(rows, "out.csv")
    assert "PCI region:\n  determined: 0\n  undetermined: 1" in summary
    assert "Clinical LS:\n  determined: 0\n  undetermined: 1" in summary


@pytest.mark.parametrize("reviewed", [1, 2])  # 2 of 3: the reviewed attempt is not the last one.
def test_reviewed_attempt_alone_supplies_row_metadata(database, tmp_path, reviewed):
    with create_session_factory(database[0]).begin() as session:
        _, saved = create(session, attempts=3, reviewed=reviewed)
    _, records, _ = export(database, tmp_path)
    assert len(records) == 1
    row = records[0]
    assert row["attempt_count"] == "3"
    assert row["reviewed_attempt_id"] == str(saved[reviewed - 1].id)
    assert row["reviewed_attempt_sequence"] == str(reviewed)
    assert row["mask_area_pixels"] == str(100 + reviewed)
    assert json.loads(row["prompt_data_json"])["box_xyxy"] == [1, 2, 10 + reviewed, 20]
    assert float(row["selected_score"]) == pytest.approx(0.5 + reviewed / 10)


@pytest.mark.parametrize("kind", ["legacy_without_review", "missing_attempt", "foreign_attempt"])
def test_inconsistent_finalized_evaluation_aborts_export(database, tmp_path, kind):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        create(session)
        evaluation, _ = create(session, code="broken", finalize=False)
        _, (foreign,) = create(session, code="other", finalize=False)
        values = {"status": "finalized", "finalized_at": datetime.now(timezone.utc)}
        if kind == "missing_attempt":
            values |= {"reviewed_attempt_id": uuid4(), "segmentation_quality": "adequate"}
        elif kind == "foreign_attempt":
            values |= {"reviewed_attempt_id": foreign.id, "segmentation_quality": "adequate"}
        session.execute(update(Evaluation).where(Evaluation.id == evaluation.id).values(**values))
    output = tmp_path / "evaluations.csv"
    with pytest.raises(InconsistentEvaluation, match=str(evaluation.id)):
        export_experiment_b(database[0], output)
    assert not output.exists()


def test_order_is_finalized_at_then_evaluation_id(database, tmp_path):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with create_session_factory(database[0]).begin() as session:
        ids = [create(session, code=f"case-{n}")[0].id for n in range(4)]
        times = [base + timedelta(hours=2), base, base + timedelta(hours=1), base + timedelta(hours=1)]
        for eid, moment in zip(ids, times):
            session.execute(update(Evaluation).where(Evaluation.id == eid).values(finalized_at=moment))
    tied = sorted([ids[2], ids[3]])
    expected = [ids[1], *tied, ids[0]]
    rows = read_rows(database[0])
    assert [row["evaluation_id"] for row in rows] == expected
    assert [UUID(r["evaluation_id"]) for r in export(database, tmp_path)[1]] == expected


def test_csv_contains_no_private_fields_or_paths(database, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:SECRET-PASSWORD@host/db")
    with create_session_factory(database[0]).begin() as session:
        create(session, attempts=2)
    _, _, content = export(database, tmp_path)
    for forbidden in ("storage_path", "mask_storage_path", "DATABASE_URL", "SECRET", "postgresql",
                      "images/", "masks/", ".png", str(tmp_path), "base64", "logits"):
        assert forbidden not in content


def test_export_does_not_modify_database(database, tmp_path):
    with create_session_factory(database[0]).begin() as session:
        create(session, attempts=2, reviewed=1)
        create(session, code="draft", finalize=False)
    before = snapshot(database[0])
    export(database, tmp_path)
    assert snapshot(database[0]) == before


def test_script_runs_without_finalized_evaluations(database, tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("export_experiment_b", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "ENV_FILE", tmp_path / "missing.env")  # Never read the developer's .env.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused@127.0.0.1/unused")
    monkeypatch.setattr(script, "create_database_engine", lambda settings: database[0])
    output = tmp_path / "out" / "evaluations.csv"
    assert script.main(["--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8").strip() == ",".join(COLUMNS)
    printed = capsys.readouterr().out
    assert "Exported 0 finalized evaluations" in printed and "unused" not in printed

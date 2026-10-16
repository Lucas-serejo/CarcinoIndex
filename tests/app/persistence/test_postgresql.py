"""Real PostgreSQL tests; each test owns a random schema, never public tables."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend.app.persistence.database import create_session_factory
from backend.app.persistence.models import Base, ClinicalCase, Evaluation, Image, SegmentationAttempt
from backend.app.persistence.repository import ExperimentRepository

pytestmark = pytest.mark.postgresql


def seed(session):
    repo = ExperimentRepository(session)
    case = repo.create_case("anonymous-001")
    image = repo.add_image(case_id=case.id,
                           storage_path=f"images/{uuid4().hex}.png", width=32, height=24, sha256="a" * 64)
    return repo.create_evaluation(image_id=image.id, pci_region_id=0, annotator_code="expert-001")


def attempt(repo, evaluation_id):
    return repo.add_attempt(evaluation_id=evaluation_id, prompt_type="box",
                            prompt_data={"box_xyxy": [1, 2, 20, 22], "multimask_output": True},
                            mask_storage_path=f"masks/{uuid4().hex}.png",
                            sam_metadata={"selected_score": 0.91, "model_name": "sam2.1_hiera_small"})


@pytest.mark.parametrize("clinical_ls", [None, 0, 1, 2, 3])
def test_round_trip_multiple_attempts_and_clinical_label(database, clinical_ls):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        evaluation = seed(session)
        eid = evaluation.id
        assert evaluation.clinical_ls is None and evaluation.annotator_confidence is None
        assert evaluation.status == "draft" and evaluation.finalized_at is None
        repo = ExperimentRepository(session)
        assert attempt(repo, eid).sequence_number == 1
        reviewed = attempt(repo, eid)
        assert reviewed.sequence_number == 2
        aid = reviewed.id
        repo.finalize_evaluation(eid, clinical_ls=clinical_ls, annotator_confidence=0.7 if clinical_ls is not None else None, reviewed_attempt_id=aid, segmentation_quality="adequate")
    with factory() as session:
        repo = ExperimentRepository(session)
        loaded = repo.get_evaluation(eid)
        assert loaded.clinical_ls == clinical_ls and loaded.annotator_confidence == (0.7 if clinical_ls is not None else None)
        assert loaded.reviewed_attempt_id == aid and loaded.segmentation_quality == "adequate"
        assert loaded.created_at.tzinfo and loaded.finalized_at.tzinfo
        assert loaded.image.case.anonymous_patient_code == "anonymous-001"
        attempts = repo.list_attempts(eid)
        assert [a.sequence_number for a in attempts] == [1, 2]
        assert attempts[0].sam_metadata["selected_score"] == 0.91
        assert attempts[0].prompt_data["multimask_output"] is True
        assert "clinical_ls" not in SegmentationAttempt.__table__.columns
        with pytest.raises(ValueError, match="finalized"):
            attempt(repo, eid)
        with pytest.raises(ValueError, match="finalized"):
            repo.finalize_evaluation(eid, clinical_ls=1, reviewed_attempt_id=aid, segmentation_quality="adequate")


@pytest.mark.parametrize("field,value", [("pci_region_id", -1), ("pci_region_id", 13), ("clinical_ls", 4), ("clinical_ls", -1), ("annotator_confidence", 0.8), ("annotator_confidence", 1.1), ("annotator_confidence", -0.1), ("annotator_confidence", float("nan")), ("status", "unknown"), ("status", "finalized"), ("annotator_code", " ")])
def test_evaluation_constraints(database, field, value):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        evaluation = seed(session)
        with pytest.raises(IntegrityError), session.begin_nested():
            setattr(evaluation, field, value)
            session.flush()


@pytest.mark.parametrize("field,value", [("width", 0), ("height", -1), ("sha256", "z" * 64), ("storage_path", ""), ("case_id", uuid4())])
def test_image_constraints(database, field, value):
    with create_session_factory(database[0]).begin() as session:
        evaluation = seed(session)
        image = session.get(Image, evaluation.image_id)
        with pytest.raises(IntegrityError), session.begin_nested():
            setattr(image, field, value)
            session.flush()


@pytest.mark.parametrize("clinical_ls", [-1, 4])
def test_database_rejects_finalized_without_valid_ls(database, clinical_ls):
    with create_session_factory(database[0]).begin() as session:
        evaluation = seed(session)
        with pytest.raises(IntegrityError), session.begin_nested():
            evaluation.status = "finalized"
            evaluation.finalized_at = datetime.now(timezone.utc)
            evaluation.clinical_ls = clinical_ls
            session.flush()


@pytest.mark.parametrize("field,value", [("sequence_number", 0), ("prompt_type", "automatic"), ("prompt_data", []), ("sam_metadata", None), ("mask_storage_path", ""), ("evaluation_id", uuid4())])
def test_attempt_constraints(database, field, value):
    with create_session_factory(database[0]).begin() as session:
        evaluation = seed(session)
        row = attempt(ExperimentRepository(session), evaluation.id)
        with pytest.raises(IntegrityError), session.begin_nested():
            setattr(row, field, value)
            session.flush()


def test_unique_sequence_foreign_keys_and_rollback(database):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        evaluation = seed(session)
        repo = ExperimentRepository(session)
        first = attempt(repo, evaluation.id)
        second = attempt(repo, evaluation.id)
        with pytest.raises(IntegrityError), session.begin_nested():
            second.sequence_number = first.sequence_number
            session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.delete(evaluation)
            session.flush()
    with pytest.raises(RuntimeError):
        with factory.begin() as session:
            case_id = ExperimentRepository(session).create_case("rollback").id
            raise RuntimeError("abort")
    with factory() as session:
        assert session.get(ClinicalCase, case_id) is None


def test_concurrent_attempts_have_distinct_sequences(database):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        eid = seed(session).id
    def append(_):
        with factory.begin() as session:
            return attempt(ExperimentRepository(session), eid).sequence_number
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, range(2))) == [1, 2]


def test_migration_matches_models_and_downgrades(database):
    engine, config = database
    with engine.begin() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert len(inspect(connection).get_table_names()) == 5


def test_optional_context_migration_upgrades_current_schema_and_reverses(database):
    engine, config = database
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002_segmentation_review")
        assert not next(c for c in inspect(connection).get_columns("evaluations") if c["name"] == "pci_region_id")["nullable"]
        command.upgrade(config, "head")
        assert next(c for c in inspect(connection).get_columns("evaluations") if c["name"] == "pci_region_id")["nullable"]
        checks = {c["name"] for c in inspect(connection).get_check_constraints("evaluations")}
        assert "ck_evaluation_finalized_ls" not in checks
        assert "ck_evaluation_confidence_requires_ls" in checks
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.downgrade(config, "0002_segmentation_review")
        checks = {c["name"] for c in inspect(connection).get_check_constraints("evaluations")}
        assert "ck_evaluation_finalized_ls" in checks
        assert "ck_evaluation_confidence_requires_ls" not in checks


def test_database_rejects_confidence_on_finalized_undetermined_ls(database):
    with create_session_factory(database[0]).begin() as session:
        evaluation = seed(session)
        repo = ExperimentRepository(session)
        saved = attempt(repo, evaluation.id)
        repo.finalize_evaluation(evaluation.id, clinical_ls=None,
                                 reviewed_attempt_id=saved.id, segmentation_quality="adequate")
        with pytest.raises(IntegrityError, match="ck_evaluation_confidence_requires_ls"), session.begin_nested():
            evaluation.annotator_confidence = 0.8
            session.flush()


@pytest.mark.parametrize("quality,has_attempt", [
    ("unknown", True), ("Adequate", True), ("", True),
    ("adequate", False), ("partially_adequate", False), (None, True),
])
def test_segmentation_review_constraints(database, quality, has_attempt):
    with create_session_factory(database[0]).begin() as session:
        evaluation = seed(session)
        saved = attempt(ExperimentRepository(session), evaluation.id)
        with pytest.raises(IntegrityError), session.begin_nested():
            evaluation.reviewed_attempt_id = saved.id if has_attempt else None
            evaluation.segmentation_quality = quality
            session.flush()


def test_incremental_migration_preserves_legacy_finalized_evaluation(database):
    from sqlalchemy import text
    engine, config = database
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_experiment")
        case_id, image_id, eid = uuid4(), uuid4(), uuid4()
        connection.execute(text("INSERT INTO clinical_cases (id, anonymous_patient_code) VALUES (:id, 'legacy')"), {"id": case_id})
        connection.execute(text("INSERT INTO images (id, case_id, storage_path, width, height, sha256) VALUES (:id, :case_id, 'images/legacy.png', 32, 24, :hash)"), {"id": image_id, "case_id": case_id, "hash": "a" * 64})
        connection.execute(text("INSERT INTO evaluations (id, image_id, pci_region_id, annotator_code, clinical_ls, status, finalized_at) VALUES (:id, :image_id, 6, 'legacy', 2, 'finalized', now())"), {"id": eid, "image_id": image_id})
        command.upgrade(config, "head")
        record = connection.execute(text("SELECT status, clinical_ls, reviewed_attempt_id, segmentation_quality FROM evaluations WHERE id = :id"), {"id": eid}).one()
        assert tuple(record) == ("finalized", 2, None, None)
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        checks = {c["name"]: c["sqltext"] for c in inspect(connection).get_check_constraints("evaluations")}
        assert "ck_evaluation_segmentation_quality" in checks
        assert "ck_evaluation_segmentation_review_pair" in checks
        command.downgrade(config, "0001_experiment")
        assert "reviewed_attempt_id" not in {c["name"] for c in inspect(connection).get_columns("evaluations")}
        assert connection.execute(text("SELECT clinical_ls FROM evaluations WHERE id = :id"), {"id": eid}).scalar_one() == 2
        command.upgrade(config, "head")


def test_concurrent_finalizations_allow_only_one_review(database):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        eid = seed(session).id
        aid = attempt(ExperimentRepository(session), eid).id
    def finalize(quality):
        try:
            with factory.begin() as session:
                ExperimentRepository(session).finalize_evaluation(
                    eid, clinical_ls=2, reviewed_attempt_id=aid, segmentation_quality=quality,
                )
            return "finalized"
        except ValueError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(finalize, ["adequate", "inadequate"])) == ["finalized", "rejected"]

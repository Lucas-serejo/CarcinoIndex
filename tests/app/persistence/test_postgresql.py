"""Real PostgreSQL tests; each test owns a random schema, never public tables."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.app.persistence.database import create_session_factory
from backend.app.persistence.models import Base, ClinicalCase, Evaluation, Image, SegmentationAttempt
from backend.app.persistence.repository import ExperimentRepository

pytestmark = pytest.mark.postgresql


@pytest.fixture
def database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database.")
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("TEST_DATABASE_URL must use postgresql+psycopg.")
    schema = "test_" + uuid4().hex
    admin = create_engine(url)
    engine = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine, config
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def seed(session):
    repo = ExperimentRepository(session)
    case = repo.create_case("anonymous-001")
    image = repo.add_image(case_id=case.id, original_filename="synthetic.png",
                           storage_path=f"images/{uuid4().hex}.png", width=32, height=24, sha256="a" * 64)
    return repo.create_evaluation(image_id=image.id, pci_region_id=0, annotator_code="expert-001")


def attempt(repo, evaluation_id):
    return repo.add_attempt(evaluation_id=evaluation_id, prompt_type="box",
                            prompt_data={"box_xyxy": [1, 2, 20, 22], "multimask_output": True},
                            mask_storage_path=f"masks/{uuid4().hex}.png",
                            sam_metadata={"selected_score": 0.91, "model_name": "sam2.1_hiera_small"})


def test_round_trip_multiple_attempts_and_clinical_label(database):
    factory = create_session_factory(database[0])
    with factory.begin() as session:
        evaluation = seed(session)
        eid = evaluation.id
        assert evaluation.clinical_ls is None and evaluation.confidence is None
        assert evaluation.status == "draft" and evaluation.finalized_at is None
        repo = ExperimentRepository(session)
        assert attempt(repo, eid).sequence_number == 1
        assert attempt(repo, eid).sequence_number == 2
        repo.finalize_evaluation(eid, clinical_ls=2, confidence=0.7)
    with factory() as session:
        repo = ExperimentRepository(session)
        loaded = repo.get_evaluation(eid)
        assert loaded.clinical_ls == 2 and loaded.confidence == 0.7
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
            repo.finalize_evaluation(eid, clinical_ls=1)


@pytest.mark.parametrize("field,value", [("pci_region_id", -1), ("pci_region_id", 13), ("clinical_ls", 4), ("clinical_ls", -1), ("confidence", 1.1), ("confidence", -0.1), ("confidence", float("nan")), ("status", "unknown"), ("status", "finalized"), ("annotator_code", " ")])
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

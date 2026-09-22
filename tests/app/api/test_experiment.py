"""Lifecycle HTTP behavior against isolated PostgreSQL and real local storage."""

import hashlib
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.persistence.database import create_session_factory
from backend.app.persistence.models import ClinicalCase, Evaluation, Image
from backend.app.persistence.repository import ExperimentRepository
from backend.app.services.segmentation_service import SegmentationService
from backend.app.storage.local import LocalStorage
from test_api import APIFakeSegmenter, animated_png, encoded_image


pytestmark = pytest.mark.postgresql
BOX = {"prompt_type": "box", "box": "[2,2,25,20]"}


@pytest.fixture
def api(database, tmp_path):
    sessions = create_session_factory(database[0])
    storage = LocalStorage(tmp_path)
    fake = APIFakeSegmenter()
    app = create_app(
        settings=Settings(max_upload_bytes=2048, max_image_width=64,
                          max_image_height=64, max_image_pixels=2048),
        segmentation_service=SegmentationService(fake), session_factory=sessions, storage=storage,
    )
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=sessions, storage=storage, fake=fake)


def create_case(api):
    response = api.client.post("/api/v1/cases", json={"anonymous_patient_code": "PATIENT-001"})
    assert response.status_code == 201, response.text
    return response.json()["case_id"]


def upload(api, case_id, content=None, media_type="image/png"):
    return api.client.post(f"/api/v1/cases/{case_id}/images", files={
        "image": ("private-original-name.png", encoded_image("PNG") if content is None else content, media_type),
    })


def create_evaluation(api):
    image = upload(api, create_case(api))
    assert image.status_code == 201, image.text
    response = api.client.post(f"/api/v1/images/{image.json()['image_id']}/evaluations",
                               json={"pci_region_id": 6, "annotator_code": "MED01"})
    assert response.status_code == 201, response.text
    return response.json()


def test_case_creation_persists_and_duplicate_codes_are_allowed(api):
    ids = [create_case(api), create_case(api)]
    assert ids[0] != ids[1]
    with api.sessions() as session:
        for case_id in ids:
            case = ExperimentRepository(session).get_case(UUID(case_id))
            assert case.anonymous_patient_code == "PATIENT-001"
            assert case.created_at is not None


@pytest.mark.parametrize("body", [
    {"anonymous_patient_code": value} for value in ["", " \t\n", "x" * 129]
] + [{"anonymous_patient_code": "CODE", "email": "unsupported"}])
def test_invalid_case_is_not_persisted(api, body):
    assert api.client.post("/api/v1/cases", json=body).status_code == 422
    with api.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ClinicalCase)) == 0


@pytest.mark.parametrize("image_format,media_type,suffix", [
    ("JPEG", "image/jpeg", ".jpg"), ("PNG", "image/png", ".png"),
])
def test_upload_preserves_original_bytes_and_safe_metadata(api, image_format, media_type, suffix):
    case_id = create_case(api)
    content = encoded_image(image_format)
    response = upload(api, case_id, content, media_type)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["case_id"] == case_id
    assert (body["width"], body["height"]) == (32, 24)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert "storage_path" not in body
    assert "private-original-name" not in response.text
    assert str(api.storage.root) not in response.text
    with api.sessions() as session:
        record = ExperimentRepository(session).get_image(UUID(body["image_id"]))
        assert re.fullmatch(r"images/[0-9a-f]{32}" + re.escape(suffix), record.storage_path)
        assert api.storage.read(record.storage_path) == content
        assert record.sha256 == body["sha256"]
        assert (record.width, record.height) == (32, 24)
        assert "private-original-name" not in str(record.__dict__)


def test_missing_case_creates_no_file(api):
    assert upload(api, uuid4()).status_code == 404
    assert not list(api.storage.root.rglob("*"))
    with api.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Image)) == 0


@pytest.mark.parametrize("content,media_type,status", [
    (b"", "image/png", 422), (b"invalid", "image/png", 422),
    (encoded_image("PNG"), "image/jpeg", 415),
    (encoded_image("JPEG"), "application/octet-stream", 415),
    (encoded_image("GIF"), "image/png", 415),
    (animated_png(), "image/png", 415),
    (b"x" * 2049, "image/png", 413),
    (encoded_image("PNG", size=(65, 24)), "image/png", 413),
    (encoded_image("PNG", size=(24, 65)), "image/png", 413),
    (encoded_image("PNG", size=(64, 64)), "image/png", 413),
])
def test_invalid_upload_creates_no_record_or_file(api, content, media_type, status):
    response = upload(api, create_case(api), content, media_type)
    assert response.status_code == status, response.text
    assert not list(api.storage.root.rglob("*"))
    with api.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Image)) == 0


@pytest.mark.parametrize("stage", ["before_flush", "before_commit"])
def test_database_failure_deletes_only_new_image(api, stage):
    case_id = create_case(api)
    assert upload(api, case_id).status_code == 201
    previous = {path: path.read_bytes() for path in api.storage.root.glob("images/*")}

    def fail(*args):
        raise RuntimeError("private database connection details")

    event.listen(Session, stage, fail)
    try:
        response = upload(api, case_id)
    finally:
        event.remove(Session, stage, fail)
    assert response.status_code == 500
    assert "private" not in response.text
    assert {path: path.read_bytes() for path in api.storage.root.glob("images/*")} == previous
    with api.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Image)) == 1


def test_draft_defaults(api):
    body = create_evaluation(api)
    assert body["status"] == "draft"
    assert body["clinical_ls"] is body["annotator_confidence"] is body["finalized_at"] is None
    with api.sessions() as session:
        record = session.get(Evaluation, UUID(body["evaluation_id"]))
        assert record.status == "draft" and record.pci_region_id == 6
        assert record.annotator_code == "MED01"
        assert record.clinical_ls is record.annotator_confidence is record.finalized_at is None


@pytest.mark.parametrize("patch", [
    {"clinical_ls": 2}, {"annotator_confidence": 0.9}, {"unexpected": "value"},
    {"pci_region_id": -1}, {"pci_region_id": 13}, {"pci_region_id": True},
    {"annotator_code": " \t\n"}, {"annotator_code": "x" * 129},
])
def test_invalid_evaluation_request(api, patch):
    image_id = upload(api, create_case(api)).json()["image_id"]
    response = api.client.post(f"/api/v1/images/{image_id}/evaluations",
                               json={"pci_region_id": 6, "annotator_code": "MED01", **patch})
    assert response.status_code == 422
    with api.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Evaluation)) == 0


def test_missing_image_and_evaluation(api):
    assert api.client.post(f"/api/v1/images/{uuid4()}/evaluations",
                           json={"pci_region_id": 6, "annotator_code": "MED01"}).status_code == 404
    assert api.client.post(f"/api/v1/evaluations/{uuid4()}/finalize",
                           json={"clinical_ls": 2}).status_code == 404


@pytest.mark.parametrize("confidence", [None, 0, 0.9, 1])
@pytest.mark.parametrize("clinical_ls", [0, 1, 2, 3])
def test_finalize_without_attempts_persists_manual_assessment(api, confidence, clinical_ls):
    evaluation = create_evaluation(api)
    eid = evaluation["evaluation_id"]
    body = {"clinical_ls": clinical_ls}
    if confidence is not None:
        body["annotator_confidence"] = confidence
    response = api.client.post(f"/api/v1/evaluations/{eid}/finalize", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "finalized"
    assert response.json()["clinical_ls"] == clinical_ls
    assert response.json()["annotator_confidence"] == confidence
    assert response.json()["finalized_at"] is not None
    assert api.client.post(f"/api/v1/evaluations/{eid}/finalize", json=body).status_code == 409
    with api.sessions() as session:
        repo = ExperimentRepository(session)
        record = repo.get_evaluation(UUID(eid))
        assert record.clinical_ls == clinical_ls and record.annotator_confidence == confidence
        assert record.status == "finalized" and record.finalized_at is not None
        assert repo.list_attempts(UUID(eid)) == []


@pytest.mark.parametrize("body", [
    {}, {"clinical_ls": None},
    *[{"clinical_ls": value} for value in [-1, 4, 1.5, True, "2"]],
    *[{"clinical_ls": 2, "annotator_confidence": value} for value in [-0.1, 1.1, True, "0.9"]],
])
def test_invalid_finalization_keeps_draft(api, body):
    eid = create_evaluation(api)["evaluation_id"]
    assert api.client.post(f"/api/v1/evaluations/{eid}/finalize", json=body).status_code == 422
    with api.sessions() as session:
        assert session.get(Evaluation, UUID(eid)).status == "draft"


def test_complete_http_lifecycle_without_cuda(api):
    """All experimental records originate in HTTP requests; SAM is the only fake."""
    evaluation = create_evaluation(api)
    eid = evaluation["evaluation_id"]
    url = f"/api/v1/evaluations/{eid}/segmentations"
    response = api.client.post(url, data=BOX)
    assert response.status_code == 201, response.text
    assert response.json()["sequence_number"] == 1
    assert api.client.post(f"/api/v1/evaluations/{eid}/finalize",
                           json={"clinical_ls": 2, "annotator_confidence": 0.9}).status_code == 200
    assert api.client.post(url, data=BOX).status_code == 409
    assert len(api.fake.calls) == 1
    with api.sessions() as session:
        repo = ExperimentRepository(session)
        attempts = repo.list_attempts(UUID(eid))
        assert len(attempts) == 1
        assert api.storage.read(attempts[0].mask_storage_path)
        assert repo.get_evaluation(UUID(eid)).clinical_ls == 2

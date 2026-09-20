import base64
import io
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.persistence.database import create_session_factory
from backend.app.persistence.repository import ExperimentRepository
from backend.app.services.segmentation_service import SegmentationService
from backend.app.storage.local import LocalStorage
from test_api import APIFakeSegmenter, encoded_image


BOX = {"prompt_type": "box", "box": "[2,2,25,20]", "multimask_output": "false"}
POINTS = {"prompt_type": "points", "points": "[[10,10],[2,2]]",
          "labels": "[1,0]", "multimask_output": "true"}


@pytest.fixture
def persisted_api(database, tmp_path):
    sessions = create_session_factory(database[0])
    storage = LocalStorage(tmp_path)
    stored = storage.save(encoded_image("PNG"), category="images", suffix=".png")
    with sessions.begin() as session:
        repo = ExperimentRepository(session)
        case = repo.create_case("synthetic")
        image = repo.add_image(case_id=case.id, storage_path=stored.path,
                              width=32, height=24, sha256=stored.sha256)
        eid = repo.create_evaluation(image_id=image.id, pci_region_id=6,
                                     annotator_code="test").id
    fake = APIFakeSegmenter()
    app = create_app(settings=Settings(), segmentation_service=SegmentationService(fake),
                     session_factory=sessions, storage=storage)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=sessions, storage=storage,
                              eid=eid, fake=fake, image_path=stored.path,
                              url=f"/api/v1/evaluations/{eid}/segmentations")


@pytest.mark.postgresql
def test_box_and_points_are_committed_with_png_and_sequence(persisted_api):
    api = persisted_api
    for sequence, fields, expected in [
        (1, BOX, {"box_xyxy": [2, 2, 25, 20], "multimask_output": False}),
        (2, POINTS, {"points_xy": [[10, 10], [2, 2]], "labels": [1, 0],
                     "multimask_output": True}),
    ]:
        response = api.client.post(api.url, data=fields)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["evaluation_id"] == str(api.eid)
        assert body["sequence_number"] == sequence
        assert body["region"] == {"region_id": 6, "region_name": "pelvis"}
        png = base64.b64decode(body["mask"]["data"], validate=True)
        with Image.open(io.BytesIO(png)) as mask:
            assert mask.format == "PNG" and mask.size == (32, 24)
            assert set(np.unique(np.asarray(mask))) == {0, 255}
        with api.sessions() as session:
            repo = ExperimentRepository(session)
            attempts = repo.list_attempts(api.eid)
            assert len(attempts) == sequence
            attempt = attempts[-1]
            assert attempt.id == UUID(body["attempt_id"])
            assert attempt.prompt_type == fields["prompt_type"]
            assert attempt.prompt_data == expected
            assert attempt.sam_metadata == body["metadata"]
            assert not {"masks", "logits", "image"} & attempt.sam_metadata.keys()
            assert api.storage.read(attempt.mask_storage_path) == png
            evaluation = repo.get_evaluation(api.eid)
            assert evaluation.status == "draft" and evaluation.clinical_ls is None
        pixels, prompt = api.fake.calls[-1]
        assert pixels.dtype == np.uint8 and pixels.shape == (24, 32, 3)
        assert np.all(pixels == [120, 80, 40])
        assert prompt.multimask_output is expected["multimask_output"]
        assert str(api.storage.root) not in response.text


@pytest.mark.postgresql
def test_missing_and_finalized_evaluations_do_not_infer(persisted_api):
    api = persisted_api
    assert api.client.post(f"/api/v1/evaluations/{uuid4()}/segmentations", data=BOX).status_code == 404
    with api.sessions.begin() as session:
        ExperimentRepository(session).finalize_evaluation(api.eid, clinical_ls=2)
    assert api.client.post(api.url, data=BOX).status_code == 409
    assert api.fake.calls == []
    assert not list(api.storage.root.glob("masks/*"))


@pytest.mark.postgresql
@pytest.mark.parametrize("failure_stage", ["flush", "commit"])
def test_database_failure_rolls_back_and_deletes_only_new_mask(persisted_api, failure_stage):
    api = persisted_api
    assert api.client.post(api.url, data=BOX).status_code == 201
    previous = set(api.storage.root.glob("masks/*"))

    def fail(session, *args):
        if session.new:
            raise RuntimeError("private database connection details")
        if failure_stage == "commit":
            raise RuntimeError("private database connection details")

    name = "before_flush" if failure_stage == "flush" else "before_commit"
    event.listen(Session, name, fail)
    try:
        response = api.client.post(api.url, data=POINTS)
    finally:
        event.remove(Session, name, fail)
    assert response.status_code == 500
    assert "private" not in response.text
    assert set(api.storage.root.glob("masks/*")) == previous
    assert api.storage.read(api.image_path)
    with api.sessions() as session:
        assert len(ExperimentRepository(session).list_attempts(api.eid)) == 1


@pytest.mark.parametrize("fields", [BOX, POINTS])
@pytest.mark.parametrize("commit_fails", [False, True])
def test_http_storage_transaction_without_postgresql(tmp_path, fields, commit_fails):
    """Exercise HTTP + SAM fake + real filesystem even without a test database."""
    storage = LocalStorage(tmp_path)
    source = storage.save(encoded_image("PNG"), category="images", suffix=".png")
    eid = uuid4()
    session = Mock(spec=Session)
    session.get.return_value = SimpleNamespace(status="draft", pci_region_id=6,
                                               image=SimpleNamespace(storage_path=source.path))
    session.scalar.side_effect = [SimpleNamespace(status="draft"), None]
    session.flush.side_effect = lambda: setattr(session.add.call_args.args[0], "id", uuid4())

    class Sessions:
        @contextmanager
        def __call__(self):
            yield session

        @contextmanager
        def begin(self):
            yield session
            if commit_fails:
                raise RuntimeError("secret commit failure")

    app = create_app(settings=Settings(), segmentation_service=SegmentationService(APIFakeSegmenter()),
                     session_factory=Sessions(), storage=storage)
    with TestClient(app) as client:
        response = client.post(f"/api/v1/evaluations/{eid}/segmentations", data=fields)
    if commit_fails:
        assert response.status_code == 500
        assert "secret" not in response.text
        assert not list(tmp_path.glob("masks/*"))
    else:
        assert response.status_code == 201, response.text
        attempt = session.add.call_args.args[0]
        body = response.json()
        assert body["sequence_number"] == 1
        assert body["region"]["region_id"] == 6
        assert attempt.prompt_data["multimask_output"] == (fields is POINTS)
        assert storage.read(attempt.mask_storage_path) == base64.b64decode(body["mask"]["data"])
    assert storage.read(source.path)


@pytest.mark.postgresql
@pytest.mark.parametrize("fields", [
    {**BOX, "region_id": "0"}, {**BOX, "ls_score": "2"},
    {**BOX, "box": "[1,2,3]"}, {**BOX, "box": "[0,0,100,100]"},
])
def test_invalid_fields_create_no_attempt(persisted_api, fields):
    api = persisted_api
    assert api.client.post(api.url, data=fields).status_code == 422
    assert not list(api.storage.root.glob("masks/*"))
    with api.sessions() as session:
        assert ExperimentRepository(session).list_attempts(api.eid) == []

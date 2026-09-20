from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def test_persistence_engine_is_owned_only_during_lifespan(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from backend.app.services.segmentation_service import SegmentationService
    from test_api import APIFakeSegmenter

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/unused")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    engine = Mock()
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr("backend.app.main.create_database_engine", create_engine)
    app = create_app(settings=Settings(), segmentation_service=SegmentationService(APIFakeSegmenter()))
    create_engine.assert_not_called()
    with TestClient(app):
        create_engine.assert_called_once()
        assert app.state.session_factory is not None
        assert app.state.storage.root == tmp_path.resolve()
        engine.dispose.assert_not_called()
    engine.dispose.assert_called_once()
    assert app.state.session_factory is None and app.state.storage is None


def test_real_lifespan_requires_checkpoint_configuration() -> None:
    app = create_app(settings=Settings(sam2_checkpoint_path=None))
    with pytest.raises(RuntimeError, match="SAM2_CHECKPOINT_PATH"):
        with TestClient(app):
            pass


def test_real_lifespan_fails_explicitly_for_missing_checkpoint(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(sam2_checkpoint_path=tmp_path / "missing.pt")
    )
    with pytest.raises(FileNotFoundError, match="missing.pt"):
        with TestClient(app):
            pass


def test_lifespan_loads_once_and_closes_on_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.touch()
    instances: list[object] = []

    class FakeRealSegmenter:
        is_loaded = False

        def __init__(self, **kwargs: object) -> None:
            self.device = kwargs["device"]
            self.dtype = kwargs["dtype"]
            self.load_count = 0
            self.close_count = 0
            instances.append(self)

        def load(self) -> None:
            self.load_count += 1
            self.is_loaded = True

        def close(self) -> None:
            self.close_count += 1
            self.is_loaded = False

    monkeypatch.setattr("backend.app.main.SAM2Segmenter", FakeRealSegmenter)
    app = create_app(settings=Settings(sam2_checkpoint_path=checkpoint))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        instance = instances[0]
        assert instance.load_count == 1  # type: ignore[attr-defined]
        assert instance.close_count == 0  # type: ignore[attr-defined]

    assert instance.load_count == 1  # type: ignore[attr-defined]
    assert instance.close_count == 1  # type: ignore[attr-defined]
    assert app.state.segmentation_service is None

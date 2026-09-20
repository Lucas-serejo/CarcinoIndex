"""FastAPI dependencies for process-local application services."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.errors import APIError
from backend.app.services.segmentation_service import SegmentationService
from backend.app.storage.local import LocalStorage


def get_segmentation_service(request: Request) -> SegmentationService:
    service = getattr(request.app.state, "segmentation_service", None)
    if service is None:
        raise APIError(503, "model_unavailable", "Segmentation service unavailable.")
    return service


def get_session_factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise APIError(503, "persistence_unavailable", "Persistence is not configured.")
    return factory


def get_storage(request: Request) -> LocalStorage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise APIError(503, "persistence_unavailable", "Storage is not configured.")
    return storage

"""FastAPI dependencies for process-local application services."""

from __future__ import annotations

from fastapi import Request

from backend.app.api.errors import APIError
from backend.app.services.segmentation_service import SegmentationService


def get_segmentation_service(request: Request) -> SegmentationService:
    service = getattr(request.app.state, "segmentation_service", None)
    if service is None:
        raise APIError(503, "model_unavailable", "Segmentation service unavailable.")
    return service

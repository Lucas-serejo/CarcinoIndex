"""Safe process health information."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_segmentation_service
from backend.app.schemas import HealthCheckResponse
from backend.app.services.segmentation_service import SegmentationService


router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Check API and model status",
    description="Returns API status and model information, including loaded state, device, and precision.",
    responses={503: {"description": "Segmentation service unavailable."}},
)
def health_check(
    service: SegmentationService = Depends(get_segmentation_service),
) -> HealthCheckResponse:
    return HealthCheckResponse(status="ok", model=service.model_status())

"""Application routers."""

from fastapi import APIRouter

from .health import router as health_router
from .pci import router as pci_router
from .segmentation import router as segmentation_router


api_router = APIRouter()
api_router.include_router(pci_router)
api_router.include_router(segmentation_router)

__all__ = ["api_router", "health_router"]

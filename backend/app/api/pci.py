"""Stateless API endpoints for PCI region catalog and composition."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from backend.app.api.errors import APIError
from backend.app.domain.pci import PCIObservation, PCI_REGIONS, compose_pci
from backend.app.schemas import (
    PCICalculateRequest,
    PCICompositionResponse,
    RegionsResponse,
)


router = APIRouter(prefix="/pci", tags=["pci"])


@router.get("/regions", response_model=RegionsResponse)
def list_regions() -> RegionsResponse:
    return RegionsResponse(regions=[asdict(region) for region in PCI_REGIONS])


@router.post("/calculate", response_model=PCICompositionResponse)
def calculate_pci(payload: PCICalculateRequest) -> PCICompositionResponse:
    try:
        observations = tuple(
            PCIObservation(**observation.model_dump())
            for observation in payload.observations
        )
        composition = compose_pci(
            observations,
            protocol_id=payload.protocol_id,
            protocol_version=payload.protocol_version,
        )
    except ValueError as exc:
        raise APIError(422, "invalid_pci_observations", str(exc)) from exc
    return PCICompositionResponse(**asdict(composition))

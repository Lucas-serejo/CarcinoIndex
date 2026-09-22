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


router = APIRouter(prefix="/pci", tags=["PCI"])


@router.get(
    "/regions",
    response_model=RegionsResponse,
    summary="List PCI regions",
    description="Returns the catalog of 13 PCI regions with their identifiers and names.",
)
def list_regions() -> RegionsResponse:
    return RegionsResponse(regions=[asdict(region) for region in PCI_REGIONS])


@router.post(
    "/calculate",
    response_model=PCICompositionResponse,
    summary="Calculate PCI from clinical LS assessments",
    description=(
        "Composes PCI from user-provided clinical LS assessments, using the highest LS per region. "
        "Returns a subtotal and pending regions; the total is available only when all 13 regions are assessed."
    ),
    responses={422: {"description": "Invalid fields, protocol, or LS assessments."}},
)
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

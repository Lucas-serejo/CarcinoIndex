"""Pydantic contracts exposed by the M3 HTTP API."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ModelHealthResponse(BaseModel):
    loaded: bool
    name: str
    device: str
    dtype: str


class HealthCheckResponse(BaseModel):
    status: Literal["ok"]
    model: ModelHealthResponse


class RegionResponse(BaseModel):
    region_id: int
    code: str
    display_name: str


class RegionsResponse(BaseModel):
    regions: list[RegionResponse]


class RegionSelectionResponse(BaseModel):
    region_id: int
    region_name: str


class LSAssessmentResponse(BaseModel):
    ls_score: int
    source: Literal["user"]


class MaskResponse(BaseModel):
    encoding: Literal["png_base64"] = "png_base64"
    media_type: Literal["image/png"] = "image/png"
    width: int
    height: int
    data: str


class SegmentationResponse(BaseModel):
    analysis_id: UUID
    status: Literal["completed"] = "completed"
    region: RegionSelectionResponse
    ls_assessment: LSAssessmentResponse | None
    metadata: dict[str, Any]
    mask: MaskResponse


class PCIObservationRequest(BaseModel):
    observation_id: str = Field(min_length=1)
    analysis_id: str | None = None
    region_id: int = Field(ge=0, le=12)
    ls_score: int = Field(ge=0, le=3)
    ls_source: Literal["user"]


class PCICalculateRequest(BaseModel):
    protocol_id: Literal["sugarbaker_pci"]
    protocol_version: Literal["project-defined-v1"]
    observations: list[PCIObservationRequest]


class RegionalPCIScoreResponse(BaseModel):
    region_id: int
    region_name: str
    ls_score: int
    source_observation_id: str
    observations_count: int
    aggregation: Literal["maximum"]


class PCICompositionResponse(BaseModel):
    status: Literal["incomplete", "complete"]
    regional_scores: list[RegionalPCIScoreResponse]
    assessed_regions: list[int]
    pending_regions: list[int]
    subtotal: int
    pci_total: int | None
    maximum_possible_total: Literal[39]
    protocol_id: Literal["sugarbaker_pci"]
    protocol_version: Literal["project-defined-v1"]

"""API-safe contracts for the specialist-led experimental lifecycle."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


PseudonymousCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anonymous_patient_code: PseudonymousCode = Field(
        description="Pseudonymous experimental identifier only; do not supply personal information.",
    )


class CaseResponse(BaseModel):
    case_id: UUID
    anonymous_patient_code: str
    created_at: datetime


class ImageResponse(BaseModel):
    image_id: UUID
    case_id: UUID
    width: int
    height: int
    sha256: str
    created_at: datetime


class CreateEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pci_region_id: int = Field(strict=True, ge=0, le=12)
    annotator_code: PseudonymousCode = Field(description="Pseudonymous specialist identifier.")


class FinalizeEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinical_ls: int = Field(strict=True, ge=0, le=3, description="Clinical LS supplied manually by the specialist.")
    annotator_confidence: float | None = Field(default=None, strict=True, ge=0, le=1)


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evaluation_id: UUID = Field(validation_alias="id")
    image_id: UUID
    pci_region_id: int
    annotator_code: str
    status: Literal["draft", "finalized"]
    clinical_ls: int | None
    annotator_confidence: float | None
    created_at: datetime
    finalized_at: datetime | None

"""API-safe contracts for the specialist-led experimental lifecycle."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


PseudonymousCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
SegmentationQuality = Literal["adequate", "partially_adequate", "inadequate"]


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

    pci_region_id: int | None = Field(strict=True, ge=0, le=12)
    annotator_code: PseudonymousCode = Field(description="Pseudonymous specialist identifier.")


class FinalizeEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_attempt_id: UUID
    segmentation_quality: SegmentationQuality = Field(description="Human qualitative review of the displayed segmentation, not clinical validation or ground truth.")
    clinical_ls: int | None = Field(strict=True, ge=0, le=3, description="Clinical LS supplied manually by the specialist, or null when undetermined.")
    annotator_confidence: float | None = Field(default=None, strict=True, ge=0, le=1)

    @model_validator(mode="after")
    def confidence_requires_ls(self):
        if self.clinical_ls is None and self.annotator_confidence is not None:
            raise ValueError("annotator_confidence requires clinical_ls.")
        return self


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evaluation_id: UUID = Field(validation_alias="id")
    image_id: UUID
    pci_region_id: int | None
    annotator_code: str
    status: Literal["draft", "finalized"]
    clinical_ls: int | None
    annotator_confidence: float | None
    reviewed_attempt_id: UUID | None
    segmentation_quality: SegmentationQuality | None
    created_at: datetime
    finalized_at: datetime | None

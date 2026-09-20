"""Concrete experiment operations. Caller owns the transaction; never commit here."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ClinicalCase, Evaluation, Image, SegmentationAttempt


class ExperimentRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_case(self, anonymous_patient_code: str) -> ClinicalCase:
        case = ClinicalCase(anonymous_patient_code=anonymous_patient_code)
        self.session.add(case)
        self.session.flush()
        return case

    def add_image(self, *, case_id: UUID, storage_path: str,
                  width: int, height: int, sha256: str) -> Image:
        image = Image(case_id=case_id,
                      storage_path=storage_path, width=width, height=height, sha256=sha256)
        self.session.add(image)
        self.session.flush()
        return image

    def create_evaluation(self, *, image_id: UUID, pci_region_id: int,
                          annotator_code: str, clinical_ls: int | None = None,
                          annotator_confidence: float | None = None) -> Evaluation:
        evaluation = Evaluation(image_id=image_id, pci_region_id=pci_region_id,
                                annotator_code=annotator_code, clinical_ls=clinical_ls,
                                annotator_confidence=annotator_confidence)
        self.session.add(evaluation)
        self.session.flush()
        return evaluation

    def get_evaluation(self, evaluation_id: UUID) -> Evaluation | None:
        return self.session.get(Evaluation, evaluation_id)

    def list_attempts(self, evaluation_id: UUID) -> list[SegmentationAttempt]:
        return list(self.session.scalars(select(SegmentationAttempt).where(
            SegmentationAttempt.evaluation_id == evaluation_id
        ).order_by(SegmentationAttempt.sequence_number)))

    def _lock_draft(self, evaluation_id: UUID) -> Evaluation:
        evaluation = self.session.scalar(select(Evaluation).where(
            Evaluation.id == evaluation_id
        ).with_for_update().execution_options(populate_existing=True))
        if evaluation is None:
            raise LookupError("Evaluation not found.")
        if evaluation.status != "draft":
            raise ValueError("Evaluation is finalized.")
        return evaluation

    def add_attempt(self, *, evaluation_id: UUID, prompt_type: str,
                    prompt_data: dict[str, Any], mask_storage_path: str,
                    sam_metadata: dict[str, Any]) -> SegmentationAttempt:
        self._lock_draft(evaluation_id)
        last = self.session.scalar(select(func.max(SegmentationAttempt.sequence_number)).where(
            SegmentationAttempt.evaluation_id == evaluation_id
        ))
        attempt = SegmentationAttempt(evaluation_id=evaluation_id,
                                      sequence_number=(last or 0) + 1,
                                      prompt_type=prompt_type, prompt_data=prompt_data,
                                      mask_storage_path=mask_storage_path, sam_metadata=sam_metadata)
        self.session.add(attempt)
        self.session.flush()
        return attempt

    def finalize_evaluation(self, evaluation_id: UUID, *, clinical_ls: int,
                            annotator_confidence: float | None = None) -> Evaluation:
        if type(clinical_ls) is not int or clinical_ls not in range(4):
            raise ValueError("clinical_ls must be an integer between 0 and 3 to finalize.")
        evaluation = self._lock_draft(evaluation_id)
        evaluation.clinical_ls = clinical_ls
        evaluation.annotator_confidence = annotator_confidence
        evaluation.status = "finalized"
        evaluation.finalized_at = datetime.now(timezone.utc)
        self.session.flush()
        return evaluation

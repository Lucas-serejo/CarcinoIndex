"""Review request validation also runs without PostgreSQL or SAM."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.experiment import FinalizeEvaluationRequest


@pytest.mark.parametrize("quality", ["adequate", "partially_adequate", "inadequate"])
def test_review_contract_preserves_human_fields(quality):
    aid = uuid4()
    request = FinalizeEvaluationRequest.model_validate({
        "clinical_ls": 2, "annotator_confidence": 0.7,
        "reviewed_attempt_id": str(aid), "segmentation_quality": quality,
    })
    assert request.model_dump() == {
        "clinical_ls": 2, "annotator_confidence": 0.7,
        "reviewed_attempt_id": aid, "segmentation_quality": quality,
    }


@pytest.mark.parametrize("field,value", [
    ("reviewed_attempt_id", "missing"), ("segmentation_quality", "missing"),
    ("reviewed_attempt_id", None), ("segmentation_quality", None),
    ("reviewed_attempt_id", "invalid"), ("segmentation_quality", "Adequate"),
    ("segmentation_quality", "good"), ("segmentation_quality", 1),
    ("selected_score", 0.99),
])
def test_review_contract_rejects_missing_invalid_and_extra_fields(field, value):
    body = {"clinical_ls": 2, "reviewed_attempt_id": str(uuid4()), "segmentation_quality": "adequate"}
    if value == "missing":
        del body[field]
    else:
        body[field] = value
    with pytest.raises(ValidationError):
        FinalizeEvaluationRequest.model_validate(body)

"""Review request validation also runs without PostgreSQL or SAM."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.experiment import CreateEvaluationRequest, FinalizeEvaluationRequest


@pytest.mark.parametrize("region", [None, *range(13)])
def test_region_accepts_explicit_null_or_valid_id(region):
    assert CreateEvaluationRequest(pci_region_id=region, annotator_code="expert").pci_region_id == region


@pytest.mark.parametrize("region", [-1, 13, True, 1.5, "2"])
def test_region_rejects_invalid_id(region):
    with pytest.raises(ValidationError):
        CreateEvaluationRequest(pci_region_id=region, annotator_code="expert")


@pytest.mark.parametrize("confidence", [None, 0, 0.8])
def test_undetermined_ls_requires_absent_confidence(confidence):
    body = {"clinical_ls": None, "annotator_confidence": confidence,
            "reviewed_attempt_id": uuid4(), "segmentation_quality": "adequate"}
    if confidence is None:
        assert FinalizeEvaluationRequest(**body).clinical_ls is None
    else:
        with pytest.raises(ValidationError, match="annotator_confidence requires clinical_ls"):
            FinalizeEvaluationRequest(**body)


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
    ("clinical_ls", "missing"),
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

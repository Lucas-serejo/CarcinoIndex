from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.persistence.models import Evaluation, SegmentationAttempt
from backend.app.persistence.repository import ExperimentRepository, InvalidSegmentationReview


@pytest.mark.parametrize("confidence", [0, 0.8])
def test_finalize_rejects_confidence_without_ls(confidence):
    session = Mock(spec=Session)
    with pytest.raises(ValueError, match="annotator_confidence requires clinical_ls"):
        ExperimentRepository(session).finalize_evaluation(
            uuid4(), clinical_ls=None, annotator_confidence=confidence,
            reviewed_attempt_id=uuid4(), segmentation_quality="adequate",
        )
    assert session.mock_calls == []


@pytest.mark.parametrize("clinical_ls", [-1, 4, True, 1.5, "2"])
def test_finalize_rejects_invalid_ls_before_database_access(clinical_ls):
    session = Mock(spec=Session)
    with pytest.raises(ValueError, match="clinical_ls"):
        ExperimentRepository(session).finalize_evaluation(uuid4(), clinical_ls=clinical_ls, reviewed_attempt_id=uuid4(), segmentation_quality="adequate")
    assert session.mock_calls == []


@pytest.mark.parametrize("clinical_ls", [None, 0, 1, 2, 3])
def test_finalize_records_manual_ls_and_annotator_confidence(clinical_ls):
    evaluation = Evaluation(id=uuid4(), status="draft", clinical_ls=None)
    session = Mock(spec=Session)
    session.scalar.return_value = evaluation
    attempt = SegmentationAttempt(id=uuid4(), evaluation_id=evaluation.id)
    session.get.return_value = attempt
    result = ExperimentRepository(session).finalize_evaluation(
        evaluation.id, clinical_ls=clinical_ls, annotator_confidence=0.7 if clinical_ls is not None else None,
        reviewed_attempt_id=attempt.id, segmentation_quality="adequate",
    )
    assert result.reviewed_attempt_id == attempt.id
    assert result.segmentation_quality == "adequate"
    assert result.status == "finalized"
    assert result.clinical_ls == clinical_ls
    assert result.annotator_confidence == (0.7 if clinical_ls is not None else None)
    assert result.finalized_at.tzinfo is not None
    session.flush.assert_called_once()


@pytest.mark.parametrize("kind", ["missing", "foreign", "invalid_quality"])
def test_review_rejected_without_mutating_evaluation(kind):
    evaluation = Evaluation(id=uuid4(), status="draft")
    session = Mock(spec=Session)
    session.scalar.return_value = evaluation
    session.get.return_value = None if kind == "missing" else SegmentationAttempt(
        id=uuid4(), evaluation_id=uuid4() if kind == "foreign" else evaluation.id,
    )
    with pytest.raises(InvalidSegmentationReview):
        ExperimentRepository(session).finalize_evaluation(
            evaluation.id, clinical_ls=2, reviewed_attempt_id=uuid4(),
            segmentation_quality="unknown" if kind == "invalid_quality" else "adequate",
        )
    assert evaluation.status == "draft"
    assert evaluation.clinical_ls is evaluation.reviewed_attempt_id is evaluation.segmentation_quality is None
    session.flush.assert_not_called()

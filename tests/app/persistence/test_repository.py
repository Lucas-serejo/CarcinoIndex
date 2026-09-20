from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.persistence.models import Evaluation
from backend.app.persistence.repository import ExperimentRepository


@pytest.mark.parametrize("clinical_ls", [None, -1, 4, True, 1.5, "2"])
def test_finalize_rejects_invalid_ls_before_database_access(clinical_ls):
    session = Mock(spec=Session)
    with pytest.raises(ValueError, match="clinical_ls"):
        ExperimentRepository(session).finalize_evaluation(uuid4(), clinical_ls=clinical_ls)
    assert session.mock_calls == []


@pytest.mark.parametrize("clinical_ls", [0, 1, 2, 3])
def test_finalize_records_manual_ls_and_annotator_confidence(clinical_ls):
    evaluation = Evaluation(id=uuid4(), status="draft", clinical_ls=None)
    session = Mock(spec=Session)
    session.scalar.return_value = evaluation
    result = ExperimentRepository(session).finalize_evaluation(
        evaluation.id, clinical_ls=clinical_ls, annotator_confidence=0.7,
    )
    assert result.status == "finalized"
    assert result.clinical_ls == clinical_ls
    assert result.annotator_confidence == 0.7
    assert result.finalized_at.tzinfo is not None
    session.flush.assert_called_once()

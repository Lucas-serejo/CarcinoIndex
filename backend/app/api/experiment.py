"""Small HTTP orchestration for the experimental lifecycle."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.dependencies import get_session_factory, get_storage
from backend.app.api.errors import APIError
from backend.app.api.image_validation import validate_image_upload
from backend.app.persistence.repository import ExperimentRepository
from backend.app.schemas.experiment import (
    CaseResponse, CreateCaseRequest, CreateEvaluationRequest, EvaluationResponse,
    FinalizeEvaluationRequest, ImageResponse,
)
from backend.app.storage.local import LocalStorage


router = APIRouter(tags=["Experiment"])


@router.post(
    "/cases", response_model=CaseResponse, status_code=201,
    summary="Create clinical case",
    description="Create a case using a pseudonymous experimental identifier, never personal information. "
                "Repeated codes are allowed. No autonomous diagnosis is performed.",
)
def create_case(
    body: CreateCaseRequest,
    sessions: sessionmaker[Session] = Depends(get_session_factory),
) -> CaseResponse:
    try:
        with sessions.begin() as session:
            case = ExperimentRepository(session).create_case(body.anonymous_patient_code)
            response = CaseResponse(case_id=case.id, anonymous_patient_code=case.anonymous_patient_code,
                                    created_at=case.created_at)
        return response
    except Exception as exc:
        raise APIError(500, "case_creation_failed", "Could not create the clinical case.") from exc


@router.post(
    "/cases/{case_id}/images", response_model=ImageResponse, status_code=201,
    summary="Upload case image",
    description="Validate a static JPEG or PNG and store the original bytes under an opaque key. "
                "Original filenames are neither stored nor returned.",
    responses={404: {"description": "Case not found."},
               413: {"description": "Image exceeds upload or dimension limits."},
               415: {"description": "Unsupported, animated, or mismatched image format."},
               422: {"description": "Invalid image or request."}},
)
async def upload_case_image(
    case_id: UUID, request: Request, image: Annotated[UploadFile, File()],
    sessions: sessionmaker[Session] = Depends(get_session_factory),
    storage: LocalStorage = Depends(get_storage),
) -> ImageResponse:
    try:
        with sessions() as session:
            if ExperimentRepository(session).get_case(case_id) is None:
                raise APIError(404, "case_not_found", "Case not found.")
        # No database transaction remains open during upload validation or file storage.
        content, pixels, image_format = await validate_image_upload(image, request.app.state.settings)
        stored = storage.save(content, category="images", suffix=".jpg" if image_format == "JPEG" else ".png")
        try:
            with sessions.begin() as session:
                record = ExperimentRepository(session).add_image(
                    case_id=case_id, storage_path=stored.path, width=pixels.shape[1],
                    height=pixels.shape[0], sha256=stored.sha256,
                )
                response = ImageResponse(image_id=record.id, case_id=record.case_id,
                                         width=record.width, height=record.height,
                                         sha256=record.sha256, created_at=record.created_at)
        except Exception:
            storage.delete(stored.path)
            raise
        return response
    except APIError:
        raise
    except Exception as exc:
        raise APIError(500, "image_creation_failed", "Could not store the image.") from exc


@router.post(
    "/images/{image_id}/evaluations", response_model=EvaluationResponse, status_code=201,
    summary="Create image evaluation",
    description="Create a draft evaluation for one PCI region and a pseudonymous specialist. "
                "Clinical LS and confidence are accepted only at finalization.",
    responses={404: {"description": "Image not found."}},
)
def create_evaluation(
    image_id: UUID, body: CreateEvaluationRequest,
    sessions: sessionmaker[Session] = Depends(get_session_factory),
) -> EvaluationResponse:
    try:
        with sessions.begin() as session:
            repo = ExperimentRepository(session)
            if repo.get_image(image_id) is None:
                raise APIError(404, "image_not_found", "Image not found.")
            evaluation = repo.create_evaluation(image_id=image_id, **body.model_dump())
            response = EvaluationResponse.model_validate(evaluation)
        return response
    except APIError:
        raise
    except Exception as exc:
        raise APIError(500, "evaluation_creation_failed", "Could not create the evaluation.") from exc


@router.post(
    "/evaluations/{evaluation_id}/finalize", response_model=EvaluationResponse,
    summary="Finalize evaluation",
    description="Record clinical LS supplied manually by the specialist and finish the evaluation. "
                "No segmentation attempt is required. Finalization does not validate or select a "
                "reference mask and does not imply autonomous diagnosis.",
    responses={404: {"description": "Evaluation not found."},
               409: {"description": "Evaluation already finalized."}},
)
def finalize_evaluation(
    evaluation_id: UUID, body: FinalizeEvaluationRequest,
    sessions: sessionmaker[Session] = Depends(get_session_factory),
) -> EvaluationResponse:
    try:
        with sessions.begin() as session:
            try:
                evaluation = ExperimentRepository(session).finalize_evaluation(
                    evaluation_id, **body.model_dump(),
                )
            except LookupError as exc:
                raise APIError(404, "evaluation_not_found", "Evaluation not found.") from exc
            except ValueError as exc:
                raise APIError(409, "evaluation_finalized", "Evaluation is finalized.") from exc
            response = EvaluationResponse.model_validate(evaluation)
        return response
    except APIError:
        raise
    except Exception as exc:
        raise APIError(500, "finalization_failed", "Could not finalize the evaluation.") from exc

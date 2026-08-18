"""Multipart endpoint for assisted SAM 2 image segmentation."""

from __future__ import annotations

import json
import math
from typing import Annotated, Literal

import torch
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from backend.ai.segmentation import (
    BoxPrompt,
    InvalidPromptError,
    ModelNotLoadedError,
    PointsPrompt,
    SegmentationPrompt,
)
from backend.app.api.dependencies import get_segmentation_service
from backend.app.api.errors import APIError
from backend.app.api.image_validation import decode_image_upload
from backend.app.core.config import Settings
from backend.app.schemas import SegmentationResponse
from backend.app.services.segmentation_service import SegmentationService


router = APIRouter(tags=["segmentations"])


def _parse_json_array(raw: str | None, field_name: str) -> list[object] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise APIError(
            422,
            "invalid_prompt",
            f"{field_name} must be a valid JSON array.",
        ) from exc
    if not isinstance(value, list):
        raise APIError(
            422,
            "invalid_prompt",
            f"{field_name} must be a JSON array.",
        )
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(
            422,
            "invalid_prompt",
            f"{field_name} values must be numbers.",
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise APIError(
            422,
            "invalid_prompt",
            f"{field_name} values must be finite.",
        )
    return numeric


def build_prompt(
    prompt_type: Literal["box", "points"],
    *,
    box: str | None,
    points: str | None,
    labels: str | None,
    multimask_output: bool,
) -> SegmentationPrompt:
    parsed_box = _parse_json_array(box, "box")
    parsed_points = _parse_json_array(points, "points")
    parsed_labels = _parse_json_array(labels, "labels")

    if prompt_type == "box":
        if parsed_box is None or len(parsed_box) != 4:
            raise APIError(
                422,
                "invalid_prompt",
                "A box prompt requires exactly four XYXY values.",
            )
        if parsed_points is not None or parsed_labels is not None:
            raise APIError(
                422,
                "invalid_prompt",
                "points and labels must be absent for a box prompt.",
            )
        return BoxPrompt(
            tuple(_number(value, "box") for value in parsed_box),
            multimask_output,
        )

    if parsed_box is not None:
        raise APIError(
            422,
            "invalid_prompt",
            "box must be absent for a points prompt.",
        )
    if not parsed_points or parsed_labels is None:
        raise APIError(
            422,
            "invalid_prompt",
            "A points prompt requires non-empty points and labels arrays.",
        )
    if len(parsed_points) != len(parsed_labels):
        raise APIError(
            422,
            "invalid_prompt",
            "points and labels must have matching lengths.",
        )

    normalized_points: list[tuple[float, float]] = []
    for point in parsed_points:
        if not isinstance(point, list) or len(point) != 2:
            raise APIError(
                422,
                "invalid_prompt",
                "Each point must contain exactly two XY values.",
            )
        normalized_points.append(
            (_number(point[0], "points"), _number(point[1], "points"))
        )
    normalized_labels: list[int] = []
    for label in parsed_labels:
        if isinstance(label, bool) or not isinstance(label, int) or label not in (0, 1):
            raise APIError(
                422,
                "invalid_prompt",
                "Point labels may contain only integer 0 or 1.",
            )
        normalized_labels.append(label)
    return PointsPrompt(
        tuple(normalized_points),
        tuple(normalized_labels),
        multimask_output,
    )


@router.post("/segmentations", response_model=SegmentationResponse)
async def create_segmentation(
    request: Request,
    image: Annotated[UploadFile, File()],
    region_id: Annotated[int, Form(ge=0, le=12)],
    prompt_type: Annotated[Literal["box", "points"], Form()],
    box: Annotated[str | None, Form()] = None,
    points: Annotated[str | None, Form()] = None,
    labels: Annotated[str | None, Form()] = None,
    multimask_output: Annotated[bool, Form()] = True,
    ls_score: Annotated[int | None, Form(ge=0, le=3)] = None,
    ls_source: Annotated[Literal["user"], Form()] = "user",
    service: SegmentationService = Depends(get_segmentation_service),
) -> SegmentationResponse:
    request_settings: Settings | None = getattr(request.app.state, "settings", None)
    try:
        if request_settings is None:
            raise APIError(
                500,
                "configuration_error",
                "API configuration unavailable.",
            )
        decoded = await decode_image_upload(image, request_settings)
        prompt = build_prompt(
            prompt_type,
            box=box,
            points=points,
            labels=labels,
            multimask_output=multimask_output,
        )
        result = await service.segment(
            decoded,
            prompt,
            region_id=region_id,
            ls_score=ls_score,
            ls_source=ls_source,
        )
    except APIError:
        raise
    except InvalidPromptError as exc:
        raise APIError(422, "invalid_prompt", str(exc)) from exc
    except torch.cuda.OutOfMemoryError as exc:
        raise APIError(
            503,
            "cuda_out_of_memory",
            "CUDA memory was exhausted during segmentation.",
        ) from exc
    except ModelNotLoadedError as exc:
        raise APIError(503, "model_unavailable", "Segmentation model unavailable.") from exc
    except RuntimeError as exc:
        if "CUDA out of memory" in str(exc):
            raise APIError(
                503,
                "cuda_out_of_memory",
                "CUDA memory was exhausted during segmentation.",
            ) from exc
        raise APIError(
            500,
            "inference_failed",
            "Segmentation inference failed.",
        ) from exc
    except Exception as exc:
        raise APIError(
            500,
            "unexpected_inference_error",
            "An unexpected segmentation error occurred.",
        ) from exc
    finally:
        await image.close()

    return SegmentationResponse(
        analysis_id=result.analysis_id,
        region={"region_id": result.region_id, "region_name": result.region_name},
        ls_assessment=(
            {"ls_score": result.ls_score, "source": result.ls_source}
            if result.ls_score is not None
            else None
        ),
        metadata=result.metadata,
        mask={
            "width": result.mask_width,
            "height": result.mask_height,
            "data": result.mask_png_base64,
        },
    )

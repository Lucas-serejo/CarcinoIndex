"""Serialized asynchronous access to the stateful SAM 2 image predictor."""

from __future__ import annotations

import asyncio
import base64
import io
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from PIL import Image

from backend.ai.segmentation import SAM2Segmenter, SegmentationPrompt
from backend.ai.segmentation.sam_segmenter import MODEL_NAME
from backend.app.domain.pci import get_region


@dataclass(frozen=True, slots=True)
class SegmentationServiceResult:
    analysis_id: UUID
    region_id: int
    region_name: str
    ls_score: int | None
    ls_source: str | None
    metadata: dict[str, object]
    mask_png_base64: str
    mask_width: int
    mask_height: int


class SegmentationService:
    """Own one process-local lock for one stateful segmenter instance."""

    def __init__(self, segmenter: SAM2Segmenter) -> None:
        self.segmenter = segmenter
        self.lock = asyncio.Lock()

    async def segment(
        self,
        image: np.ndarray,
        prompt: SegmentationPrompt,
        *,
        region_id: int,
        ls_score: int | None = None,
        ls_source: str = "user",
    ) -> SegmentationServiceResult:
        region = get_region(region_id)
        if ls_score is not None and (
            isinstance(ls_score, bool) or ls_score not in range(4)
        ):
            raise ValueError("ls_score must be between 0 and 3.")
        if ls_source != "user":
            raise ValueError("ls_source must be 'user'.")

        async with self.lock:
            result = await asyncio.to_thread(self.segmenter.infer, image, prompt)

        mask = np.asarray(result.selected_mask, dtype=bool)
        if mask.ndim != 2:
            raise RuntimeError("SAM 2 returned an invalid selected mask.")
        png_buffer = io.BytesIO()
        Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(
            png_buffer,
            format="PNG",
        )
        height, width = mask.shape
        return SegmentationServiceResult(
            analysis_id=uuid4(),
            region_id=region_id,
            region_name=region.code,
            ls_score=ls_score,
            ls_source=ls_source if ls_score is not None else None,
            metadata=result.to_metadata_dict(),
            mask_png_base64=base64.b64encode(png_buffer.getvalue()).decode("ascii"),
            mask_width=int(width),
            mask_height=int(height),
        )

    def model_status(self) -> dict[str, Any]:
        return {
            "loaded": bool(self.segmenter.is_loaded),
            "name": MODEL_NAME,
            "device": str(self.segmenter.device),
            "dtype": str(self.segmenter.dtype),
        }

    def close(self) -> None:
        self.segmenter.close()

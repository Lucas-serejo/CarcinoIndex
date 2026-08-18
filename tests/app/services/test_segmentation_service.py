from __future__ import annotations

import asyncio
import base64
import io
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from PIL import Image

from backend.ai.segmentation import BoxPrompt, PointsPrompt, SegmentationResult
from backend.app.services.segmentation_service import SegmentationService


def fake_result(prompt_type: str = "box") -> SegmentationResult:
    mask = np.zeros((24, 32), dtype=bool)
    mask[4:20, 8:24] = True
    return SegmentationResult(
        masks=np.stack([mask]),
        scores=np.asarray([0.91], dtype=np.float32),
        logits=None,
        selected_index=0,
        selected_mask=mask,
        selected_score=0.91,
        prompt_type=prompt_type,
        prompt_data={"test": True},
        image_shape=(24, 32, 3),
        model_name="sam2.1_hiera_small",
        model_config="configs/sam2.1/sam2.1_hiera_s.yaml",
        checkpoint_name="sam2.1_hiera_small.pt",
        device="cuda",
        dtype="float32",
        load_time_seconds=1.0,
        embedding_time_seconds=0.2,
        prediction_time_seconds=0.1,
        peak_vram_bytes=1234,
    )


class FakeSegmenter:
    is_loaded = True
    device = "cuda"
    dtype = "float32"

    def __init__(self, *, delay: float = 0.0, failure: Exception | None = None) -> None:
        self.calls: list[tuple[np.ndarray, Any]] = []
        self.delay = delay
        self.failure = failure
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()
        self.closed = False

    def infer(self, image: np.ndarray, prompt: Any) -> SegmentationResult:
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append((image, prompt))
            if self.delay:
                time.sleep(self.delay)
            if self.failure is not None:
                raise self.failure
            return fake_result("points" if isinstance(prompt, PointsPrompt) else "box")
        finally:
            with self.guard:
                self.active -= 1

    def close(self) -> None:
        self.closed = True


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def test_box_image_and_prompt_reach_wrapper() -> None:
    segmenter = FakeSegmenter()
    service = SegmentationService(segmenter)  # type: ignore[arg-type]
    image = np.zeros((24, 32, 3), dtype=np.uint8)
    prompt = BoxPrompt((1.0, 2.0, 20.0, 21.0))

    result = run(service.segment(image, prompt, region_id=0, ls_score=2))

    assert segmenter.calls == [(image, prompt)]
    assert result.region_name == "central"
    assert result.ls_score == 2
    assert result.ls_source == "user"


def test_points_prompt_reaches_wrapper() -> None:
    segmenter = FakeSegmenter()
    service = SegmentationService(segmenter)  # type: ignore[arg-type]
    prompt = PointsPrompt(((4.0, 5.0),), (1,))
    run(service.segment(np.zeros((24, 32, 3), dtype=np.uint8), prompt, region_id=6))
    assert segmenter.calls[0][1] is prompt


def test_png_base64_is_valid_and_preserves_dimensions() -> None:
    service = SegmentationService(FakeSegmenter())  # type: ignore[arg-type]
    result = run(
        service.segment(
            np.zeros((24, 32, 3), dtype=np.uint8),
            BoxPrompt((1.0, 1.0, 20.0, 20.0)),
            region_id=1,
        )
    )
    png = base64.b64decode(result.mask_png_base64, validate=True)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(png)) as decoded:
        assert decoded.format == "PNG"
        assert decoded.size == (32, 24)
    assert (result.mask_width, result.mask_height) == (32, 24)


def test_metadata_and_uuid_are_preserved() -> None:
    service = SegmentationService(FakeSegmenter())  # type: ignore[arg-type]
    result = run(
        service.segment(
            np.zeros((24, 32, 3), dtype=np.uint8),
            BoxPrompt((1.0, 1.0, 20.0, 20.0)),
            region_id=2,
        )
    )
    assert UUID(str(result.analysis_id)) == result.analysis_id
    assert result.metadata["selected_score"] == pytest.approx(0.91)
    assert result.metadata["checkpoint_name"] == "sam2.1_hiera_small.pt"


def test_missing_ls_remains_none() -> None:
    service = SegmentationService(FakeSegmenter())  # type: ignore[arg-type]
    result = run(
        service.segment(
            np.zeros((24, 32, 3), dtype=np.uint8),
            BoxPrompt((1.0, 1.0, 20.0, 20.0)),
            region_id=0,
        )
    )
    assert result.ls_score is None
    assert result.ls_source is None


def test_service_does_not_create_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = SegmentationService(FakeSegmenter())  # type: ignore[arg-type]
    run(
        service.segment(
            np.zeros((24, 32, 3), dtype=np.uint8),
            BoxPrompt((1.0, 1.0, 20.0, 20.0)),
            region_id=0,
        )
    )
    assert list(tmp_path.iterdir()) == []


def test_inference_exception_is_propagated() -> None:
    failure = RuntimeError("controlled failure")
    service = SegmentationService(FakeSegmenter(failure=failure))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="controlled failure"):
        run(
            service.segment(
                np.zeros((24, 32, 3), dtype=np.uint8),
                BoxPrompt((1.0, 1.0, 20.0, 20.0)),
                region_id=0,
            )
        )


def test_lock_prevents_concurrent_predictor_entry() -> None:
    segmenter = FakeSegmenter(delay=0.05)
    service = SegmentationService(segmenter)  # type: ignore[arg-type]
    image = np.zeros((24, 32, 3), dtype=np.uint8)

    async def concurrent_calls() -> None:
        await asyncio.gather(
            service.segment(
                image,
                BoxPrompt((1.0, 1.0, 20.0, 20.0)),
                region_id=0,
            ),
            service.segment(
                image,
                PointsPrompt(((4.0, 5.0),), (1,)),
                region_id=1,
            ),
        )

    run(concurrent_calls())
    assert segmenter.max_active == 1
    assert len(segmenter.calls) == 2


def test_model_status_is_safe() -> None:
    service = SegmentationService(FakeSegmenter())  # type: ignore[arg-type]
    status = service.model_status()
    assert status == {
        "loaded": True,
        "name": "sam2.1_hiera_small",
        "device": "cuda",
        "dtype": "float32",
    }
    assert "path" not in status

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import torch

from backend.ai.segmentation import BoxPrompt, SAM2Segmenter


CHECKPOINT_ENV = os.environ.get("SAM2_CHECKPOINT")


@pytest.mark.sam2_integration
@pytest.mark.skipif(
    not CHECKPOINT_ENV or not torch.cuda.is_available(),
    reason="Set SAM2_CHECKPOINT and provide CUDA to run the integration test.",
)
def test_real_sam2_box_inference_on_synthetic_image() -> None:
    checkpoint = Path(CHECKPOINT_ENV)
    image = np.zeros((128, 128, 3), dtype=np.uint8)
    image[32:96, 32:96] = (220, 130, 90)
    segmenter = SAM2Segmenter(checkpoint, device="cuda", dtype="float32")
    try:
        segmenter.load()
        result = segmenter.infer(
            image,
            BoxPrompt((28.0, 28.0, 100.0, 100.0)),
        )
        assert result.selected_mask.shape == (128, 128)
        assert result.selected_mask.dtype == np.bool_
        assert segmenter.has_image is False
    finally:
        segmenter.close()

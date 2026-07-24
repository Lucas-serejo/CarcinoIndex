from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.ai.segmentation.sam_segmenter import (
    ImageNotSetError,
    InvalidPromptError,
    SAM2Segmenter,
)


class FakePredictor:
    def __init__(self) -> None:
        self.image: np.ndarray | None = None
        self.was_reset = False

    def set_image(self, image: np.ndarray) -> None:
        self.image = image

    def reset_predictor(self) -> None:
        self.was_reset = True
        self.image = None

    def predict(self, **_: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        masks = np.zeros((3, 32, 48), dtype=bool)
        masks[0, 2:5, 2:5] = True
        masks[1, 5:20, 8:30] = True
        masks[2, 10:15, 10:15] = True
        scores = np.asarray([0.2, 0.91, 0.4], dtype=np.float32)
        logits = np.zeros((3, 256, 256), dtype=np.float32)
        return masks, scores, logits


@pytest.fixture
def checkpoint(tmp_path: Path) -> Path:
    path = tmp_path / "sam2.1_hiera_small.pt"
    path.touch()
    return path


@pytest.fixture
def ready_segmenter(checkpoint: Path) -> SAM2Segmenter:
    segmenter = SAM2Segmenter(checkpoint, device="cpu")
    segmenter._model = object()
    segmenter._predictor = FakePredictor()
    segmenter.set_image(np.zeros((32, 48, 3), dtype=np.uint8))
    return segmenter


def test_load_rejects_missing_checkpoint(tmp_path: Path) -> None:
    segmenter = SAM2Segmenter(tmp_path / "missing.pt", device="cpu")
    with pytest.raises(FileNotFoundError, match="checkpoint not found"):
        segmenter.load()


def test_load_rejects_unavailable_cuda(
    checkpoint: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.ai.segmentation.sam_segmenter.torch.cuda.is_available",
        lambda: False,
    )
    segmenter = SAM2Segmenter(checkpoint, device="cuda")
    with pytest.raises(RuntimeError, match="CUDA is unavailable"):
        segmenter.load()


@pytest.mark.parametrize(
    "image",
    [
        np.zeros((32, 48), dtype=np.uint8),
        np.zeros((1, 32, 48, 3), dtype=np.uint8),
    ],
)
def test_set_image_rejects_invalid_dimensions(
    ready_segmenter: SAM2Segmenter, image: np.ndarray
) -> None:
    with pytest.raises(ValueError, match="shape HxWx3"):
        ready_segmenter.set_image(image)


def test_set_image_rejects_non_rgb_channels(
    ready_segmenter: SAM2Segmenter,
) -> None:
    with pytest.raises(ValueError, match="three RGB channels"):
        ready_segmenter.set_image(np.zeros((32, 48, 4), dtype=np.uint8))


def test_box_rejects_wrong_number_of_values(
    ready_segmenter: SAM2Segmenter,
) -> None:
    with pytest.raises(InvalidPromptError, match="exactly four"):
        ready_segmenter.segment_with_box([1, 2, 3])


def test_box_rejects_inverted_coordinates(
    ready_segmenter: SAM2Segmenter,
) -> None:
    with pytest.raises(InvalidPromptError, match="x_min < x_max"):
        ready_segmenter.segment_with_box([20, 5, 10, 25])


def test_box_rejects_coordinates_outside_image(
    ready_segmenter: SAM2Segmenter,
) -> None:
    with pytest.raises(InvalidPromptError, match="image bounds"):
        ready_segmenter.segment_with_box([0, 0, 49, 20])


def test_points_reject_mismatched_labels(
    ready_segmenter: SAM2Segmenter,
) -> None:
    with pytest.raises(InvalidPromptError, match="matching lengths"):
        ready_segmenter.segment_with_points([[10, 10], [20, 20]], [1])


def test_points_reject_invalid_label(ready_segmenter: SAM2Segmenter) -> None:
    with pytest.raises(InvalidPromptError, match="only 0 or 1"):
        ready_segmenter.segment_with_points([[10, 10]], [2])


def test_points_reject_coordinate_outside_image(
    ready_segmenter: SAM2Segmenter,
) -> None:
    with pytest.raises(InvalidPromptError, match="image bounds"):
        ready_segmenter.segment_with_points([[48, 10]], [1])


def test_segmentation_requires_an_image(checkpoint: Path) -> None:
    segmenter = SAM2Segmenter(checkpoint, device="cpu")
    segmenter._model = object()
    segmenter._predictor = FakePredictor()
    with pytest.raises(ImageNotSetError, match=r"set_image\(\)"):
        segmenter.segment_with_box([1, 1, 10, 10])


def test_highest_score_mask_is_selected(
    ready_segmenter: SAM2Segmenter,
) -> None:
    result = ready_segmenter.segment_with_box([2, 2, 30, 25])
    assert result.selected_index == 1
    assert result.selected_score == pytest.approx(0.91)
    assert result.selected_mask.dtype == np.bool_
    np.testing.assert_array_equal(result.selected_mask, result.masks[1])
    assert result.prompt_type == "box"


def test_point_prompt_returns_structured_data(
    ready_segmenter: SAM2Segmenter,
) -> None:
    result = ready_segmenter.segment_with_points([[20, 15], [2, 2]], [1, 0])
    assert result.prompt_type == "points"
    assert result.prompt_data == {
        "points_xy": [[20.0, 15.0], [2.0, 2.0]],
        "labels": [1, 0],
    }
    assert result.image_shape == (32, 48, 3)
    assert result.model_name == "sam2.1_hiera_small"
    assert result.checkpoint_name == "sam2.1_hiera_small.pt"

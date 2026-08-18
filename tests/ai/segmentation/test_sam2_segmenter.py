from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from backend.ai.segmentation.sam_segmenter import (
    ImageNotSetError,
    InvalidPromptError,
    SAM2Segmenter,
    UnsupportedPromptError,
)
from backend.ai.segmentation.types import BoxPrompt, PointsPrompt


class FakePredictor:
    def __init__(
        self,
        *,
        fail_on_predict: bool = False,
        mutate_on_set: bool = False,
    ) -> None:
        self.image: np.ndarray | None = None
        self.was_reset = False
        self.reset_count = 0
        self.set_image_count = 0
        self.predict_count = 0
        self.fail_on_predict = fail_on_predict
        self.mutate_on_set = mutate_on_set

    def set_image(self, image: np.ndarray) -> None:
        self.set_image_count += 1
        if self.mutate_on_set:
            image[:] = 255
        self.image = image

    def reset_predictor(self) -> None:
        self.was_reset = True
        self.reset_count += 1
        self.image = None

    def predict(self, **_: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        self.predict_count += 1
        if self.fail_on_predict:
            raise RuntimeError("predict failed deliberately")
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
def loaded_segmenter(checkpoint: Path) -> SAM2Segmenter:
    segmenter = SAM2Segmenter(checkpoint, device="cpu")
    segmenter._model = object()
    segmenter._predictor = FakePredictor()
    return segmenter


@pytest.fixture
def ready_segmenter(loaded_segmenter: SAM2Segmenter) -> SAM2Segmenter:
    segmenter = loaded_segmenter
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


def test_box_prompt_creation() -> None:
    prompt = BoxPrompt((1.0, 2.0, 30.0, 40.0))
    assert prompt.box == (1.0, 2.0, 30.0, 40.0)
    assert prompt.multimask_output is True


def test_points_prompt_creation() -> None:
    prompt = PointsPrompt(((10.0, 20.0), (2.0, 3.0)), (1, 0), False)
    assert prompt.points == ((10.0, 20.0), (2.0, 3.0))
    assert prompt.labels == (1, 0)
    assert prompt.multimask_output is False


def test_infer_with_box_calls_expected_methods(
    loaded_segmenter: SAM2Segmenter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    expected = object()
    monkeypatch.setattr(
        loaded_segmenter,
        "set_image",
        lambda image: calls.append(("set_image", image.shape)),
    )
    monkeypatch.setattr(
        loaded_segmenter,
        "segment_with_box",
        lambda box, multimask_output: (
            calls.append(("box", box, multimask_output)) or expected
        ),
    )
    monkeypatch.setattr(
        loaded_segmenter,
        "clear_image",
        lambda: calls.append("clear_image"),
    )

    result = loaded_segmenter.infer(
        np.zeros((32, 48, 3), dtype=np.uint8),
        BoxPrompt((1.0, 2.0, 30.0, 25.0), False),
    )

    assert result is expected
    assert calls[0] == ("set_image", (32, 48, 3))
    assert calls[1] == ("box", (1.0, 2.0, 30.0, 25.0), False)
    assert calls[2] == "clear_image"


def test_infer_with_points_calls_expected_methods(
    loaded_segmenter: SAM2Segmenter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    expected = object()
    monkeypatch.setattr(loaded_segmenter, "set_image", lambda image: None)
    monkeypatch.setattr(
        loaded_segmenter,
        "segment_with_points",
        lambda points, labels, multimask_output: (
            calls.append((points, labels, multimask_output)) or expected
        ),
    )

    result = loaded_segmenter.infer(
        np.zeros((32, 48, 3), dtype=np.uint8),
        PointsPrompt(((20.0, 15.0), (2.0, 2.0)), (1, 0)),
    )

    assert result is expected
    assert calls == [(((20.0, 15.0), (2.0, 2.0)), (1, 0), True)]


def test_infer_clears_image_after_success(loaded_segmenter: SAM2Segmenter) -> None:
    result = loaded_segmenter.infer(
        np.zeros((32, 48, 3), dtype=np.uint8),
        BoxPrompt((2.0, 2.0, 30.0, 25.0)),
    )
    assert result.prompt_type == "box"
    assert loaded_segmenter.has_image is False
    assert loaded_segmenter.is_loaded is True


def test_infer_clears_image_after_predict_failure(
    loaded_segmenter: SAM2Segmenter,
) -> None:
    predictor = FakePredictor(fail_on_predict=True)
    loaded_segmenter._predictor = predictor

    with pytest.raises(RuntimeError, match="predict failed deliberately"):
        loaded_segmenter.infer(
            np.zeros((32, 48, 3), dtype=np.uint8),
            BoxPrompt((2.0, 2.0, 30.0, 25.0)),
        )

    assert loaded_segmenter.has_image is False
    assert predictor.reset_count >= 1


def test_infer_does_not_mutate_input(loaded_segmenter: SAM2Segmenter) -> None:
    loaded_segmenter._predictor = FakePredictor(mutate_on_set=True)
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    original = image.copy()

    loaded_segmenter.infer(image, BoxPrompt((2.0, 2.0, 30.0, 25.0)))

    np.testing.assert_array_equal(image, original)


def test_two_sequential_inferences_keep_model_loaded(
    loaded_segmenter: SAM2Segmenter,
) -> None:
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    first = loaded_segmenter.infer(
        image, BoxPrompt((2.0, 2.0, 30.0, 25.0))
    )
    second = loaded_segmenter.infer(
        image, PointsPrompt(((20.0, 15.0),), (1,))
    )

    assert first.prompt_type == "box"
    assert second.prompt_type == "points"
    assert loaded_segmenter.is_loaded is True
    assert loaded_segmenter.has_image is False


def test_clear_image_is_idempotent(ready_segmenter: SAM2Segmenter) -> None:
    ready_segmenter.clear_image()
    ready_segmenter.clear_image()
    assert ready_segmenter.has_image is False
    assert ready_segmenter.is_loaded is True


def test_close_is_idempotent(ready_segmenter: SAM2Segmenter) -> None:
    ready_segmenter.close()
    ready_segmenter.close()
    assert ready_segmenter.has_image is False
    assert ready_segmenter.is_loaded is False


def test_infer_rejects_unknown_prompt(loaded_segmenter: SAM2Segmenter) -> None:
    with pytest.raises(UnsupportedPromptError, match="BoxPrompt or PointsPrompt"):
        loaded_segmenter.infer(
            np.zeros((32, 48, 3), dtype=np.uint8),
            cast(Any, object()),
        )
    assert loaded_segmenter.has_image is False


def test_metadata_is_json_serializable(ready_segmenter: SAM2Segmenter) -> None:
    result = ready_segmenter.segment_with_box([2, 2, 30, 25])
    metadata = result.to_metadata_dict()
    assert json.loads(json.dumps(metadata)) == metadata


def test_metadata_excludes_large_arrays(ready_segmenter: SAM2Segmenter) -> None:
    metadata = ready_segmenter.segment_with_box(
        [2, 2, 30, 25]
    ).to_metadata_dict()
    assert "masks" not in metadata
    assert "selected_mask" not in metadata
    assert "logits" not in metadata


def test_metadata_converts_numpy_values(ready_segmenter: SAM2Segmenter) -> None:
    result = ready_segmenter.segment_with_box([2, 2, 30, 25])
    with_numpy_prompt = replace(
        result,
        prompt_data={
            "value": np.int64(7),
            "point": np.asarray([1.5, 2.5], dtype=np.float32),
        },
    )
    metadata = with_numpy_prompt.to_metadata_dict()
    assert metadata["prompt_data"] == {"value": 7, "point": [1.5, 2.5]}
    json.dumps(metadata)


def test_metadata_uses_safe_checkpoint_and_config_names(tmp_path: Path) -> None:
    checkpoint = tmp_path / "private" / "sam2.1_hiera_small.pt"
    checkpoint.parent.mkdir()
    checkpoint.touch()
    segmenter = SAM2Segmenter(checkpoint, device="cpu")
    segmenter._model = object()
    segmenter._predictor = FakePredictor()
    segmenter.set_image(np.zeros((32, 48, 3), dtype=np.uint8))

    result = segmenter.segment_with_box([2, 2, 30, 25])
    result_with_absolute_config = replace(
        result,
        model_config=str(tmp_path / "private" / "sam2.1_hiera_s.yaml"),
        checkpoint_name=str(checkpoint),
    )
    metadata = result_with_absolute_config.to_metadata_dict()

    assert metadata["checkpoint_name"] == "sam2.1_hiera_small.pt"
    assert str(tmp_path) not in json.dumps(metadata)
    assert metadata["model_config"] == "sam2.1_hiera_s.yaml"


def test_mask_area_ratio_is_correct(ready_segmenter: SAM2Segmenter) -> None:
    metadata = ready_segmenter.segment_with_box(
        [2, 2, 30, 25]
    ).to_metadata_dict()
    assert metadata["mask_area_pixels"] == 330
    assert metadata["mask_area_ratio"] == pytest.approx(330 / (32 * 48))

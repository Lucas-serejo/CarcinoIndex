"""Image segmentation with the official SAM 2.1 Hiera Small predictor."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np
import torch


MODEL_NAME = "sam2.1_hiera_small"
DEFAULT_MODEL_CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"


class ModelNotLoadedError(RuntimeError):
    """Raised when inference is requested before loading SAM 2."""


class ImageNotSetError(RuntimeError):
    """Raised when a prompt is used before setting an image."""


class InvalidPromptError(ValueError):
    """Raised when box or point prompt coordinates are invalid."""


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    """Structured SAM 2 output.

    ``selected_mask`` is boolean. ``selected_score`` is SAM 2's predicted
    mask-quality score and must not be interpreted as clinical confidence.
    """

    masks: np.ndarray
    scores: np.ndarray
    logits: np.ndarray | None
    selected_index: int
    selected_mask: np.ndarray
    selected_score: float
    prompt_type: str
    prompt_data: dict[str, Any]
    image_shape: tuple[int, int, int]
    model_name: str
    model_config: str
    checkpoint_name: str
    device: str
    dtype: str
    load_time_seconds: float | None
    embedding_time_seconds: float | None
    prediction_time_seconds: float
    peak_vram_bytes: int | None


class SAM2Segmenter:
    """Explicit-lifecycle wrapper for SAM 2.1 Hiera Small image prediction.

    Images must be RGB NumPy arrays in HWC format. ``uint8`` images use the
    official [0, 255] input convention. Floating-point images are accepted
    only in [0, 1], matching torchvision's ``ToTensor`` behavior.
    """

    def __init__(
        self,
        checkpoint_path: str | Path,
        model_config: str = DEFAULT_MODEL_CONFIG,
        device: str = "cuda",
        dtype: str = "float32",
    ) -> None:
        if not isinstance(model_config, str) or not model_config.strip():
            raise ValueError("model_config must be a non-empty logical config name.")
        if not isinstance(device, str) or not (
            device == "cpu" or device == "cuda" or device.startswith("cuda:")
        ):
            raise ValueError("device must be 'cpu', 'cuda', or 'cuda:<index>'.")

        dtype_aliases = {
            "fp32": "float32",
            "float32": "float32",
            "bf16": "bfloat16",
            "bfloat16": "bfloat16",
        }
        try:
            normalized_dtype = dtype_aliases[dtype]
        except (KeyError, TypeError) as exc:
            raise ValueError("dtype must be 'float32' or 'bfloat16'.") from exc
        if normalized_dtype == "bfloat16" and not device.startswith("cuda"):
            raise ValueError("bfloat16 is supported only with a CUDA device in M2.")

        self.checkpoint_path = Path(checkpoint_path).expanduser()
        self.model_config = model_config
        self.device = device
        self.dtype = normalized_dtype

        self._model: Any | None = None
        self._predictor: Any | None = None
        self._image_shape: tuple[int, int, int] | None = None
        self._load_time_seconds: float | None = None
        self._embedding_time_seconds: float | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._predictor is not None

    @property
    def has_image(self) -> bool:
        return self.is_loaded and self._image_shape is not None

    @property
    def load_time_seconds(self) -> float | None:
        return self._load_time_seconds

    @property
    def embedding_time_seconds(self) -> float | None:
        return self._embedding_time_seconds

    def load(self) -> SAM2Segmenter:
        """Load the checkpoint once and initialize the official image predictor."""
        if self.is_loaded:
            return self
        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(
                f"SAM 2 checkpoint not found: {self.checkpoint_path}"
            )
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"CUDA device '{self.device}' was requested but CUDA is unavailable. "
                "CPU fallback is disabled."
            )
        if self.dtype == "bfloat16" and not torch.cuda.is_bf16_supported():
            raise RuntimeError(
                "bfloat16 was requested but this CUDA device does not support it."
            )

        started = time.perf_counter()
        try:
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor

            model = build_sam2(
                self.model_config,
                str(self.checkpoint_path.resolve()),
                device=self.device,
                apply_postprocessing=False,
            )
            predictor = SAM2ImagePredictor(model)
            self._synchronize_cuda()
        except torch.cuda.OutOfMemoryError as exc:
            raise self._cuda_oom_error("loading the model", exc) from exc
        except Exception as exc:
            self._model = None
            self._predictor = None
            raise RuntimeError(
                "Failed to load SAM 2.1 Hiera Small with config "
                f"'{self.model_config}' and checkpoint "
                f"'{self.checkpoint_path.name}': {exc}"
            ) from exc

        self._model = model
        self._predictor = predictor
        self._load_time_seconds = time.perf_counter() - started
        return self

    def set_image(self, image: np.ndarray) -> None:
        """Embed a validated RGB image without manual resize or normalization."""
        self._require_loaded()
        validated = self._validate_image(image)

        if self.device.startswith("cuda"):
            torch.cuda.reset_peak_memory_stats(self.device)
        started = time.perf_counter()
        try:
            with self._inference_context():
                self._predictor.set_image(validated)
                self._synchronize_cuda()
        except torch.cuda.OutOfMemoryError as exc:
            self.clear_image()
            raise self._cuda_oom_error("embedding the image", exc) from exc
        except Exception as exc:
            self.clear_image()
            raise RuntimeError(f"SAM 2 image embedding failed: {exc}") from exc

        self._image_shape = tuple(int(value) for value in validated.shape)
        self._embedding_time_seconds = time.perf_counter() - started

    def segment_with_box(
        self,
        box: Sequence[float] | np.ndarray,
        multimask_output: bool = True,
    ) -> SegmentationResult:
        """Segment with an XYXY box in coordinates of the original image."""
        self._require_image()
        validated_box = self._validate_box(box)
        return self._predict(
            prompt_type="box",
            prompt_data={"box_xyxy": validated_box.tolist()},
            box=validated_box,
            multimask_output=multimask_output,
        )

    def segment_with_points(
        self,
        points: Sequence[Sequence[float]] | np.ndarray,
        labels: Sequence[int] | np.ndarray,
        multimask_output: bool = True,
    ) -> SegmentationResult:
        """Segment with positive (1) and negative (0) point prompts."""
        self._require_image()
        validated_points, validated_labels = self._validate_points(points, labels)
        return self._predict(
            prompt_type="points",
            prompt_data={
                "points_xy": validated_points.tolist(),
                "labels": validated_labels.tolist(),
            },
            point_coords=validated_points,
            point_labels=validated_labels,
            multimask_output=multimask_output,
        )

    def clear_image(self) -> None:
        """Clear image embeddings while keeping the loaded model."""
        if self._predictor is not None:
            reset = getattr(self._predictor, "reset_predictor", None)
            if callable(reset):
                reset()
        self._image_shape = None
        self._embedding_time_seconds = None

    def close(self) -> None:
        """Release model and predictor references and clear cached CUDA blocks."""
        self.clear_image()
        self._predictor = None
        self._model = None
        self._load_time_seconds = None
        if self.device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _predict(
        self,
        *,
        prompt_type: str,
        prompt_data: dict[str, Any],
        point_coords: np.ndarray | None = None,
        point_labels: np.ndarray | None = None,
        box: np.ndarray | None = None,
        multimask_output: bool,
    ) -> SegmentationResult:
        started = time.perf_counter()
        try:
            with self._inference_context():
                masks, scores, logits = self._predictor.predict(
                    point_coords=point_coords,
                    point_labels=point_labels,
                    box=box,
                    multimask_output=multimask_output,
                )
                self._synchronize_cuda()
        except torch.cuda.OutOfMemoryError as exc:
            raise self._cuda_oom_error("predicting a mask", exc) from exc
        except Exception as exc:
            raise RuntimeError(f"SAM 2 predictor failed for {prompt_type}: {exc}") from exc

        prediction_time = time.perf_counter() - started
        masks_array = np.asarray(masks, dtype=bool)
        scores_array = np.asarray(scores, dtype=np.float32)
        logits_array = None if logits is None else np.asarray(logits)
        if masks_array.ndim != 3 or scores_array.ndim != 1:
            raise RuntimeError(
                "SAM 2 returned unexpected mask or score dimensions: "
                f"{masks_array.shape}, {scores_array.shape}."
            )
        if masks_array.shape[0] == 0 or masks_array.shape[0] != scores_array.shape[0]:
            raise RuntimeError("SAM 2 returned inconsistent masks and scores.")

        selected_index = int(np.argmax(scores_array))
        return SegmentationResult(
            masks=masks_array,
            scores=scores_array,
            logits=logits_array,
            selected_index=selected_index,
            selected_mask=masks_array[selected_index],
            selected_score=float(scores_array[selected_index]),
            prompt_type=prompt_type,
            prompt_data=prompt_data,
            image_shape=self._image_shape,
            model_name=MODEL_NAME,
            model_config=self.model_config,
            checkpoint_name=self.checkpoint_path.name,
            device=self.device,
            dtype=self.dtype,
            load_time_seconds=self._load_time_seconds,
            embedding_time_seconds=self._embedding_time_seconds,
            prediction_time_seconds=prediction_time,
            peak_vram_bytes=self._peak_vram_bytes(),
        )

    def _validate_image(self, image: np.ndarray) -> np.ndarray:
        if not isinstance(image, np.ndarray):
            raise TypeError("image must be a numpy.ndarray.")
        if image.ndim != 3:
            raise ValueError(f"image must have shape HxWx3; got {image.shape}.")
        if image.shape[2] != 3:
            raise ValueError(f"image must have exactly three RGB channels; got {image.shape}.")
        if image.shape[0] == 0 or image.shape[1] == 0 or image.size == 0:
            raise ValueError("image must not be empty.")
        if image.dtype == np.bool_ or not (
            np.issubdtype(image.dtype, np.integer)
            or np.issubdtype(image.dtype, np.floating)
        ):
            raise TypeError(f"image dtype must be numeric RGB data; got {image.dtype}.")
        if not np.all(np.isfinite(image)):
            raise ValueError("image contains NaN or infinite values.")

        minimum = float(np.min(image))
        maximum = float(np.max(image))
        if np.issubdtype(image.dtype, np.floating):
            if minimum < 0.0 or maximum > 1.0:
                raise ValueError("floating-point RGB images must use values in [0, 1].")
        else:
            if minimum < 0.0 or maximum > 255.0:
                raise ValueError("integer RGB images must use values in [0, 255].")
            if image.dtype != np.uint8:
                image = image.astype(np.uint8)
        return np.ascontiguousarray(image)

    def _validate_box(self, box: Sequence[float] | np.ndarray) -> np.ndarray:
        raw = np.asarray(box)
        if raw.shape != (4,):
            raise InvalidPromptError("box must contain exactly four XYXY values.")
        if raw.dtype == np.bool_ or not np.issubdtype(raw.dtype, np.number):
            raise InvalidPromptError("box values must be numeric.")
        validated = raw.astype(np.float32)
        if not np.all(np.isfinite(validated)):
            raise InvalidPromptError("box values must be finite.")

        x_min, y_min, x_max, y_max = validated
        if x_min >= x_max or y_min >= y_max:
            raise InvalidPromptError("box requires x_min < x_max and y_min < y_max.")
        height, width, _ = self._image_shape
        if x_min < 0 or y_min < 0 or x_max > width or y_max > height:
            raise InvalidPromptError(
                f"box must stay within image bounds width={width}, height={height}."
            )
        return validated

    def _validate_points(
        self,
        points: Sequence[Sequence[float]] | np.ndarray,
        labels: Sequence[int] | np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        raw_points = np.asarray(points)
        raw_labels = np.asarray(labels)
        if raw_points.ndim != 2 or raw_points.shape[1:] != (2,) or len(raw_points) == 0:
            raise InvalidPromptError("points must be a non-empty Nx2 array.")
        if raw_points.dtype == np.bool_ or not np.issubdtype(raw_points.dtype, np.number):
            raise InvalidPromptError("point coordinates must be numeric.")
        if raw_labels.ndim != 1 or len(raw_labels) != len(raw_points):
            raise InvalidPromptError("points and labels must have matching lengths.")
        if raw_labels.dtype == np.bool_ or not np.issubdtype(raw_labels.dtype, np.number):
            raise InvalidPromptError("point labels must be numeric 0 or 1.")

        validated_points = raw_points.astype(np.float32)
        validated_labels = raw_labels.astype(np.int32)
        if not np.all(np.isfinite(validated_points)):
            raise InvalidPromptError("point coordinates must be finite.")
        if not np.all(raw_labels == validated_labels):
            raise InvalidPromptError("point labels must be integer values 0 or 1.")
        if not np.all(np.isin(validated_labels, (0, 1))):
            raise InvalidPromptError("point labels may contain only 0 or 1.")

        height, width, _ = self._image_shape
        x_coordinates = validated_points[:, 0]
        y_coordinates = validated_points[:, 1]
        if (
            np.any(x_coordinates < 0)
            or np.any(x_coordinates >= width)
            or np.any(y_coordinates < 0)
            or np.any(y_coordinates >= height)
        ):
            raise InvalidPromptError(
                f"points must stay within image bounds width={width}, height={height}."
            )
        return validated_points, validated_labels

    def _require_loaded(self) -> None:
        if not self.is_loaded:
            raise ModelNotLoadedError("Call load() before setting an image.")

    def _require_image(self) -> None:
        self._require_loaded()
        if not self.has_image:
            raise ImageNotSetError("Call set_image() before segmentation.")

    @contextlib.contextmanager
    def _inference_context(self) -> Iterator[None]:
        if self.dtype == "bfloat16":
            with torch.inference_mode(), torch.autocast(
                device_type="cuda", dtype=torch.bfloat16
            ):
                yield
        else:
            with torch.inference_mode():
                yield

    def _synchronize_cuda(self) -> None:
        if self.device.startswith("cuda"):
            torch.cuda.synchronize(self.device)

    def _peak_vram_bytes(self) -> int | None:
        if not self.device.startswith("cuda"):
            return None
        return int(torch.cuda.max_memory_allocated(self.device))

    def _cuda_oom_error(
        self, operation: str, cause: torch.cuda.OutOfMemoryError
    ) -> RuntimeError:
        total = int(torch.cuda.get_device_properties(self.device).total_memory)
        allocated = int(torch.cuda.memory_allocated(self.device))
        reserved = int(torch.cuda.memory_reserved(self.device))
        peak = int(torch.cuda.max_memory_allocated(self.device))
        torch.cuda.empty_cache()
        return RuntimeError(
            f"CUDA out of memory while {operation}: total={total}, "
            f"allocated={allocated}, reserved={reserved}, peak={peak} bytes. "
            "No CPU or smaller-model fallback was attempted."
        )

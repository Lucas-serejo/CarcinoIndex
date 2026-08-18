"""Internal prompt data types for SAM 2 image segmentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class BoxPrompt:
    """Bounding box prompt in original-image XYXY coordinates."""

    box: tuple[float, float, float, float]
    multimask_output: bool = True


@dataclass(frozen=True, slots=True)
class PointsPrompt:
    """Positive (1) and negative (0) points in original-image XY coordinates."""

    points: tuple[tuple[float, float], ...]
    labels: tuple[int, ...]
    multimask_output: bool = True


SegmentationPrompt: TypeAlias = BoxPrompt | PointsPrompt

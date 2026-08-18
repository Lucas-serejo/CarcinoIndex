"""SAM 2.1 image-segmentation interface."""

from .sam_segmenter import (
    ImageNotSetError,
    InvalidPromptError,
    ModelNotLoadedError,
    SAM2Segmenter,
    SegmentationResult,
    UnsupportedPromptError,
)
from .types import BoxPrompt, PointsPrompt, SegmentationPrompt

__all__ = [
    "BoxPrompt",
    "ImageNotSetError",
    "InvalidPromptError",
    "ModelNotLoadedError",
    "PointsPrompt",
    "SAM2Segmenter",
    "SegmentationPrompt",
    "SegmentationResult",
    "UnsupportedPromptError",
]

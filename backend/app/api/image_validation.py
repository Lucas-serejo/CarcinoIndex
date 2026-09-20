"""In-memory validation and decoding for JPEG and PNG uploads."""

from __future__ import annotations

import io

import numpy as np
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from backend.app.api.errors import APIError
from backend.app.core.config import Settings


SUPPORTED_MEDIA_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
}


async def decode_image_upload(
    upload: UploadFile,
    settings: Settings,
) -> np.ndarray:
    expected_format = SUPPORTED_MEDIA_TYPES.get(upload.content_type or "")
    if expected_format is None:
        raise APIError(
            415,
            "unsupported_media_type",
            "Only image/jpeg and image/png uploads are accepted.",
        )

    content = await upload.read(settings.max_upload_bytes + 1)
    return decode_image_bytes(content, settings, expected_format=expected_format)


def decode_image_bytes(
    content: bytes, settings: Settings, *, expected_format: str | None = None,
) -> np.ndarray:
    """Decode stored bytes or uploads without changing orientation or pixels."""
    if not content:
        raise APIError(422, "empty_image", "The uploaded image is empty.")
    if len(content) > settings.max_upload_bytes:
        raise APIError(
            413,
            "upload_too_large",
            "The uploaded image exceeds the configured byte limit.",
        )

    try:
        with Image.open(io.BytesIO(content)) as probe:
            actual_format = probe.format
            frame_count = int(getattr(probe, "n_frames", 1))
            animated = bool(getattr(probe, "is_animated", False))
            width, height = probe.size
            if actual_format not in SUPPORTED_MEDIA_TYPES.values():
                raise APIError(415, "unsupported_media_type", "Only JPEG and PNG are accepted.")
            if expected_format is not None and actual_format != expected_format:
                raise APIError(
                    415,
                    "media_type_mismatch",
                    "The declared media type does not match the image content.",
                )
            if animated or frame_count != 1:
                raise APIError(
                    415,
                    "animated_image_unsupported",
                    "Animated or multi-frame images are not accepted.",
                )
            if width <= 0 or height <= 0:
                raise APIError(
                    422,
                    "invalid_image",
                    "The uploaded image has invalid dimensions.",
                )
            if (
                width > settings.max_image_width
                or height > settings.max_image_height
                or width * height > settings.max_image_pixels
            ):
                raise APIError(
                    413,
                    "image_dimensions_exceeded",
                    "The uploaded image exceeds the configured dimension limits.",
                )
            probe.verify()

        with Image.open(io.BytesIO(content)) as decoded:
            decoded.load()
            rgb = decoded.convert("RGB")
            image = np.asarray(rgb, dtype=np.uint8).copy()
    except APIError:
        raise
    except Image.DecompressionBombError as exc:
        raise APIError(
            413,
            "image_dimensions_exceeded",
            "The uploaded image exceeds the configured dimension limits.",
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise APIError(
            422,
            "invalid_image",
            "The uploaded file is not a decodable JPEG or PNG image.",
        ) from exc

    if image.shape != (height, width, 3) or image.dtype != np.uint8:
        raise APIError(
            422,
            "invalid_image",
            "The uploaded image could not be converted to RGB.",
        )
    return image

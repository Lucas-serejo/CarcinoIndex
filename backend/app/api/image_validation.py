"""In-memory validation and decoding for JPEG and PNG uploads."""

from __future__ import annotations

import io
import struct
import warnings

import numpy as np
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from backend.app.api.errors import APIError
from backend.app.core.config import Settings


SUPPORTED_MEDIA_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
}


def _validate_orientation(image: Image.Image) -> None:
    """Fail closed on orientation metadata; never transform uploaded pixels."""
    try:
        with warnings.catch_warnings():
            # Pillow can warn and then treat damaged EXIF as absent.
            warnings.simplefilter("error", UserWarning)
            exif = image.getexif()
            raw = image.info.get("exif")
            if raw is not None:
                if raw.startswith(b"Exif\x00\x00"):
                    raw = raw[6:]
                if raw[:4] not in (b"II\x2a\x00", b"MM\x00\x2a"):
                    raise ValueError("Unsupported EXIF header")
                endian = "<" if raw[:2] == b"II" else ">"
                offset = struct.unpack_from(endian + "I", raw, 4)[0]
                if offset < 8:
                    raise ValueError("Invalid EXIF directory")
                count = struct.unpack_from(endian + "H", raw, offset)[0]
                if offset + 2 + 12 * count + 4 > len(raw):
                    raise ValueError("Truncated EXIF directory")
                # Inspect IFD0 entries because Pillow silently drops unknown
                # types and empty tags, which must not become "no orientation".
                for index in range(count):
                    entry = offset + 2 + 12 * index
                    tag, kind, length = struct.unpack_from(endian + "HHI", raw, entry)
                    if tag == 274:
                        value = struct.unpack_from(endian + "H", raw, entry + 8)[0]
                        if kind != 3 or length != 1 or value != 1:
                            raise ValueError("Unsupported orientation")
            orientation = exif.get(274, 1)
            if type(orientation) is not int or orientation != 1:
                raise ValueError("Unsupported orientation")
    except Exception as exc:
        # Metadata parser failures must never expose internals or reach SAM.
        raise APIError(
            422,
            "unsupported_image_orientation",
            "Image orientation metadata is unsupported or invalid. "
            "Normalize image orientation before upload.",
        ) from exc


async def decode_image_upload(
    upload: UploadFile,
    settings: Settings,
) -> np.ndarray:
    _, pixels, _ = await validate_image_upload(upload, settings)
    return pixels


async def validate_image_upload(
    upload: UploadFile, settings: Settings,
) -> tuple[bytes, np.ndarray, str]:
    """Return original validated bytes, RGB pixels, and the verified format."""
    expected_format = SUPPORTED_MEDIA_TYPES.get(upload.content_type or "")
    if expected_format is None:
        raise APIError(
            415,
            "unsupported_media_type",
            "Only image/jpeg and image/png uploads are accepted.",
        )

    content = await upload.read(settings.max_upload_bytes + 1)
    pixels = decode_image_bytes(content, settings, expected_format=expected_format)
    return content, pixels, expected_format


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
            # PNG EXIF may occur after IDAT, so inspect after the full load.
            _validate_orientation(decoded)
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

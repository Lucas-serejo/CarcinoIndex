"""Orientation safety using only generated, non-clinical JPEG/PNG images."""

import io
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from backend.app.api.errors import APIError
from backend.app.api.image_validation import decode_image_bytes
from backend.app.core.config import Settings
from test_api import encoded_image


def exif_entry(*, kind=3, count=1, value=6, endian="<"):
    """Minimal TIFF IFD0, including cases Pillow silently drops or coerces."""
    header = b"II" if endian == "<" else b"MM"
    return (b"Exif\x00\x00" + header + struct.pack(endian + "HIH", 42, 8, 1)
            + struct.pack(endian + "HHI", 274, kind, count)
            + struct.pack(endian + "H", value) + b"\x00\x00"
            + struct.pack(endian + "I", 0))


@pytest.mark.parametrize("image_format", ["JPEG", "PNG"])
@pytest.mark.parametrize("exif", [
    exif_entry(value=0), exif_entry(value=9),
    exif_entry(kind=99), exif_entry(count=0), exif_entry(count=2, value=1),
    exif_entry(kind=4, value=1), exif_entry(endian=">"),
    b"Exif\x00\x00broken", b"Exif\x00\x00", exif_entry()[:-5],
], ids=["zero", "unknown-value", "unknown-type", "empty-tag", "multiple-values",
        "wrong-type", "big-endian-rotated", "bad-header", "empty-exif", "truncated-ifd"])
def test_uninterpretable_orientation_is_rejected(image_format, exif):
    content = encoded_image(image_format, exif=exif)
    with pytest.raises(APIError) as caught:
        decode_image_bytes(content, Settings())
    assert caught.value.status_code == 422
    assert caught.value.code == "unsupported_image_orientation"


@pytest.mark.parametrize("image_format", ["JPEG", "PNG"])
@pytest.mark.parametrize("endian", ["<", ">"])
def test_normal_orientation_keeps_asymmetric_pixels(image_format, endian):
    pixels = np.zeros((24, 32, 3), dtype=np.uint8)
    pixels[:8, :12] = [240, 80, 20]
    output = io.BytesIO()
    Image.fromarray(pixels).save(output, format=image_format, exif=exif_entry(value=1, endian=endian))
    content = output.getvalue()
    with Image.open(io.BytesIO(content)) as source:
        expected = np.asarray(source.convert("RGB"))
    np.testing.assert_array_equal(decode_image_bytes(content, Settings()), expected)


@pytest.mark.parametrize("image_format", ["JPEG", "PNG"])
def test_exif_without_orientation_is_accepted(image_format):
    exif = Image.Exif()
    exif[315] = "synthetic test"
    content = encoded_image(image_format, exif=exif.tobytes())
    assert decode_image_bytes(content, Settings()).shape == (24, 32, 3)


def test_png_exif_after_pixel_data_is_rejected():
    # PNG permits ancillary EXIF after IDAT; Image.open alone may not see it.
    content = encoded_image("PNG")
    payload = b"eXIf" + exif_entry()[6:]
    chunk = (struct.pack(">I", len(payload) - 4) + payload
             + struct.pack(">I", zlib.crc32(payload)))
    content = content[:-12] + chunk + content[-12:]  # before IEND
    with pytest.raises(APIError) as caught:
        decode_image_bytes(content, Settings())
    assert caught.value.code == "unsupported_image_orientation"

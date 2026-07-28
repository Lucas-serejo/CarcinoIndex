"""Environment-backed application configuration for the CarcinoIndex API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    project_name: str = "CarcinoIndex"
    environment: str = "development"
    sam2_checkpoint_path: Path | None = None
    sam2_model_config: str = "configs/sam2.1/sam2.1_hiera_s.yaml"
    sam2_device: str = "cuda"
    sam2_dtype: str = "float32"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_width: int = 4096
    max_image_height: int = 4096
    max_image_pixels: int = 16_000_000
    api_prefix: str = "/api/v1"

    @classmethod
    def from_env(cls) -> "Settings":
        checkpoint_value = os.getenv("SAM2_CHECKPOINT_PATH", "").strip()
        api_prefix = os.getenv("API_PREFIX", "/api/v1").strip()
        if not api_prefix.startswith("/"):
            raise ValueError("API_PREFIX must start with '/'.")
        return cls(
            project_name=os.getenv("PROJECT_NAME", "CarcinoIndex"),
            environment=os.getenv("ENVIRONMENT", "development"),
            sam2_checkpoint_path=(
                Path(checkpoint_value).expanduser() if checkpoint_value else None
            ),
            sam2_model_config=os.getenv(
                "SAM2_MODEL_CONFIG",
                "configs/sam2.1/sam2.1_hiera_s.yaml",
            ),
            sam2_device=os.getenv("SAM2_DEVICE", "cuda"),
            sam2_dtype=os.getenv("SAM2_DTYPE", "float32"),
            max_upload_bytes=_positive_int(
                "MAX_UPLOAD_BYTES",
                10 * 1024 * 1024,
            ),
            max_image_width=_positive_int("MAX_IMAGE_WIDTH", 4096),
            max_image_height=_positive_int("MAX_IMAGE_HEIGHT", 4096),
            max_image_pixels=_positive_int("MAX_IMAGE_PIXELS", 16_000_000),
            api_prefix=api_prefix.rstrip("/") or "/",
        )


settings = Settings.from_env()

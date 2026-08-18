"""Run SAM 2.1 prompts on a user-provided, non-clinical local image."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ai.segmentation import (  # noqa: E402
    BoxPrompt,
    PointsPrompt,
    SAM2Segmenter,
    SegmentationPrompt,
)
from backend.ai.segmentation.sam_segmenter import (  # noqa: E402
    DEFAULT_MODEL_CONFIG,
    MODEL_NAME,
    SegmentationResult,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--dtype",
        default="float32",
        choices=("float32", "bfloat16"),
    )
    parser.add_argument("--config", default=DEFAULT_MODEL_CONFIG)
    parser.add_argument(
        "--box",
        nargs=4,
        type=float,
        required=True,
        metavar=("X_MIN", "Y_MIN", "X_MAX", "Y_MAX"),
    )
    parser.add_argument(
        "--positive-point",
        nargs=2,
        type=float,
        required=True,
        metavar=("X", "Y"),
    )
    parser.add_argument(
        "--negative-point",
        nargs=2,
        type=float,
        metavar=("X", "Y"),
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_rgb_image(path: Path) -> tuple[Image.Image, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(f"Input image not found: {path.name}")
    try:
        with Image.open(path) as source:
            source.load()
            if source.width <= 0 or source.height <= 0:
                raise ValueError("Input image has an invalid resolution.")
            rgb = source.convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(f"Unsupported or invalid image: {path.name}") from exc
    return rgb, np.asarray(rgb, dtype=np.uint8).copy()


def make_overlay(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    overlay = image.astype(np.float32).copy()
    color = np.zeros_like(overlay)
    color[..., 0] = 255
    overlay[mask] = overlay[mask] * 0.55 + color[mask] * 0.45
    return np.clip(overlay, 0, 255).astype(np.uint8)


def save_result(
    output_root: Path,
    experiment_name: str,
    image: np.ndarray,
    result: SegmentationResult,
) -> dict[str, object]:
    experiment_dir = output_root / experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    mask_relative = f"{experiment_name}/mask.png"
    overlay_relative = f"{experiment_name}/overlay.png"
    metadata_relative = f"{experiment_name}/metadata.json"

    Image.fromarray(result.selected_mask.astype(np.uint8) * 255).save(
        experiment_dir / "mask.png"
    )
    Image.fromarray(make_overlay(image, result.selected_mask)).save(
        experiment_dir / "overlay.png"
    )
    metadata = result.to_metadata_dict()
    metadata["status"] = "success"
    metadata["qualitative_notes"] = None
    write_json(experiment_dir / "metadata.json", metadata)

    return {
        "name": experiment_name,
        "status": "success",
        "score": metadata["selected_score"],
        "selected_index": metadata["selected_index"],
        "selected_mask_file": mask_relative,
        "overlay_file": overlay_relative,
        "metadata_file": metadata_relative,
        "mask_area_pixels": metadata["mask_area_pixels"],
        "mask_area_ratio": metadata["mask_area_ratio"],
        "timings_seconds": {
            "load": metadata["load_time_seconds"],
            "embedding": metadata["embedding_time_seconds"],
            "prediction": metadata["prediction_time_seconds"],
        },
        "peak_vram_bytes": metadata["peak_vram_bytes"],
        "qualitative_notes": None,
    }


def safe_error_message(
    error: Exception,
    image_path: Path,
    checkpoint_path: Path,
) -> str:
    message = str(error)
    replacements = {
        str(image_path): image_path.name,
        str(image_path.resolve()): image_path.name,
        str(checkpoint_path): checkpoint_path.name,
        str(checkpoint_path.resolve()): checkpoint_path.name,
    }
    for sensitive, safe_name in replacements.items():
        message = message.replace(sensitive, safe_name)
    return message


def build_prompts(args: argparse.Namespace) -> list[tuple[str, SegmentationPrompt]]:
    positive = tuple(float(value) for value in args.positive_point)
    prompts: list[tuple[str, SegmentationPrompt]] = [
        (
            "box",
            BoxPrompt(tuple(float(value) for value in args.box)),
        ),
        (
            "positive_point",
            PointsPrompt((positive,), (1,)),
        ),
    ]
    if args.negative_point is not None:
        negative = tuple(float(value) for value in args.negative_point)
        prompts.append(
            (
                "positive_negative_points",
                PointsPrompt((positive, negative), (1, 0)),
            )
        )
    return prompts


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    image_path = args.image.expanduser().resolve()
    checkpoint_path = args.checkpoint.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    timestamp = datetime.now(timezone.utc)

    try:
        normalized_input, image = load_rgb_image(image_path)
        if not checkpoint_path.is_file():
            raise FileNotFoundError(
                f"SAM 2 checkpoint not found: {checkpoint_path.name}"
            )
        output_root.mkdir(parents=True, exist_ok=True)
        normalized_input.save(output_root / "input.png")
    except Exception as exc:
        print(
            f"Unable to prepare real-image experiment: "
            f"{safe_error_message(exc, image_path, checkpoint_path)}",
            file=sys.stderr,
        )
        return 1

    image_hash = sha256_file(image_path)
    checkpoint_hash = sha256_file(checkpoint_path)
    experiments = build_prompts(args)
    config_path = Path(args.config)
    config_identifier = (
        config_path.name if config_path.is_absolute() else config_path.as_posix()
    )
    manifest: dict[str, Any] = {
        "experiment_id": (
            f"sam2-real-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{image_hash[:8]}"
        ),
        "timestamp_utc": timestamp.isoformat(),
        "source_image_name": image_path.name,
        "source_image_sha256": image_hash,
        "image_shape": [int(value) for value in image.shape],
        "model": MODEL_NAME,
        "checkpoint_name": checkpoint_path.name,
        "checkpoint_sha256": checkpoint_hash,
        "configuration": config_identifier,
        "device": args.device,
        "dtype": args.dtype,
        "sam2_cuda_extension_enabled": (
            importlib.util.find_spec("sam2._C") is not None
        ),
        "experiments": [],
        "qualitative_notes": None,
    }

    segmenter = SAM2Segmenter(
        checkpoint_path=checkpoint_path,
        model_config=args.config,
        device=args.device,
        dtype=args.dtype,
    )
    try:
        segmenter.load()
    except Exception as exc:
        message = safe_error_message(exc, image_path, checkpoint_path)
        for name, _ in experiments:
            manifest["experiments"].append(
                {
                    "name": name,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": message,
                    "qualitative_notes": None,
                }
            )
        write_json(output_root / "manifest.json", manifest)
        print(f"SAM 2 load failed: {message}", file=sys.stderr)
        return 1

    successes = 0
    try:
        for name, prompt in experiments:
            try:
                result = segmenter.infer(image, prompt)
                entry = save_result(output_root, name, image, result)
                manifest["experiments"].append(entry)
                successes += 1
                print(
                    f"{name}: score={result.selected_score:.6f}, "
                    f"area={entry['mask_area_pixels']} pixels, "
                    f"ratio={entry['mask_area_ratio']:.6f}"
                )
            except Exception as exc:
                message = safe_error_message(exc, image_path, checkpoint_path)
                manifest["experiments"].append(
                    {
                        "name": name,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error_message": message,
                        "qualitative_notes": None,
                    }
                )
                print(f"{name} failed: {message}", file=sys.stderr)
    finally:
        segmenter.close()
        write_json(output_root / "manifest.json", manifest)

    return 0 if successes > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run SAM 2.1 Hiera Small on a programmatically generated RGB image."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


DEFAULT_CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"
MODEL_NAME = "sam2.1_hiera_small"
OFFICIAL_ORIGIN = "https://github.com/facebookresearch/sam2.git"


class FeasibilityError(RuntimeError):
    """Raised for an explicitly classified feasibility failure."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sam2-repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--dtype", choices=("fp32", "bf16"), default="fp32")
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(repo: Path, *args: str) -> str:
    safe_repo = str(repo.resolve()).replace("\\", "/")
    result = subprocess.run(
        ["git", "-c", f"safe.directory={safe_repo}", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def resolve_config(repo: Path, logical_config: str) -> Path:
    candidates = (repo / logical_config, repo / "sam2" / logical_config)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[-1].resolve()


def validate_sam2_origin(repo: Path) -> str:
    origin = git_value(repo, "remote", "get-url", "origin")
    normalized = origin.removesuffix("/").removesuffix(".git")
    expected = OFFICIAL_ORIGIN.removesuffix(".git")
    if normalized != expected:
        raise FeasibilityError(f"Unexpected SAM 2 origin: {origin}")

    spec = importlib.util.find_spec("sam2")
    if spec is None or spec.origin is None:
        raise FeasibilityError("The sam2 package is not importable.")
    module_path = Path(spec.origin).resolve()
    try:
        return str(module_path.relative_to(repo.resolve()))
    except ValueError as exc:
        raise FeasibilityError(
            f"An old or unrelated SAM 2 installation was imported: {module_path}"
        ) from exc


def synthetic_image(size: int) -> tuple[Any, list[float]]:
    import numpy as np

    if size < 128:
        raise FeasibilityError("Image size must be at least 128 pixels.")

    yy, xx = np.mgrid[0:size, 0:size]
    image = np.empty((size, size, 3), dtype=np.uint8)
    image[..., 0] = 30 + (xx * 25 // max(size - 1, 1))
    image[..., 1] = 45 + (yy * 20 // max(size - 1, 1))
    image[..., 2] = 65

    center_x, center_y = int(size * 0.52), int(size * 0.51)
    radius_x, radius_y = int(size * 0.22), int(size * 0.18)
    lesion = (
        ((xx - center_x) / radius_x) ** 2
        + ((yy - center_y) / radius_y) ** 2
        <= 1.0
    )
    image[lesion] = (205, 115, 85)

    highlight = (
        ((xx - int(size * 0.47)) / max(int(size * 0.07), 1)) ** 2
        + ((yy - int(size * 0.45)) / max(int(size * 0.05), 1)) ** 2
        <= 1.0
    )
    image[highlight] = (235, 165, 130)

    box = [
        float(center_x - radius_x - size * 0.025),
        float(center_y - radius_y - size * 0.025),
        float(center_x + radius_x + size * 0.025),
        float(center_y + radius_y + size * 0.025),
    ]
    return image, box


def classify_error(exc: BaseException) -> str:
    message = str(exc).lower()
    missing_module = getattr(exc, "name", None)
    if isinstance(exc, ModuleNotFoundError):
        if missing_module == "torch":
            return "torch_missing"
        if missing_module == "torchvision":
            return "torchvision_missing_or_incompatible"
        if missing_module == "sam2":
            return "sam2_not_importable"
    if isinstance(exc, PermissionError):
        return "output_permission_error"
    if isinstance(exc, FileNotFoundError):
        return "missing_file_or_windows_path_error"
    if "checkpoint not found" in message:
        return "checkpoint_missing"
    if "python" in message and ("requires" in message or "incompatible" in message):
        return "python_incompatible"
    if "torchvision" in message:
        return "torchvision_missing_or_incompatible"
    if "out of memory" in message:
        return "cuda_out_of_memory"
    if "no available kernel" in message or "kernel image" in message:
        return "attention_kernel_unavailable"
    if "state_dict" in message:
        return "checkpoint_state_dict_error"
    if "config" in message or "hydra" in message:
        return "configuration_error"
    if "sam2" in message and ("import" in message or "installation" in message):
        return "sam2_import_or_installation_error"
    if "cuda" in message:
        return "cuda_error"
    return "unexpected_error"


@contextlib.contextmanager
def inference_context(torch: Any, dtype_name: str) -> Iterator[None]:
    if dtype_name == "bf16":
        if not torch.cuda.is_bf16_supported():
            raise FeasibilityError("BF16 was requested but is not supported.")
        with torch.inference_mode(), torch.autocast(
            device_type="cuda", dtype=torch.bfloat16
        ):
            yield
    else:
        with torch.inference_mode():
            yield


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = datetime.now(timezone.utc)
    repo = args.sam2_repo.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    output = args.output.expanduser().resolve()
    config_path = resolve_config(repo, args.config)
    metadata_path = output / "metadata.json"
    metadata: dict[str, Any] = {
        "timestamp_utc": started_at.isoformat(),
        "status": "error",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "model": MODEL_NAME,
        "checkpoint": checkpoint.name,
        "configuration": args.config,
        "image_size": [args.image_size, args.image_size],
        "device_requested": args.device,
        "dtype": "float32" if args.dtype == "fp32" else "bfloat16",
        "sam2_cuda_extension_disabled": True,
        "torch_compile": False,
        "clinical_image_used": False,
    }

    try:
        if args.device != "cuda":
            raise FeasibilityError(
                "M1 requires --device cuda; CPU fallback is forbidden."
            )
        if not repo.is_dir():
            raise FeasibilityError(f"SAM 2 repository not found: {repo}")
        if not checkpoint.is_file():
            raise FeasibilityError(f"Checkpoint not found: {checkpoint}")
        if not config_path.is_file():
            raise FeasibilityError(f"Configuration not found: {config_path}")

        output.mkdir(parents=True, exist_ok=True)
        probe = output / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()

        import numpy as np
        import torch
        import torchvision
        from PIL import Image

        if not torch.cuda.is_available():
            raise FeasibilityError(
                "CUDA is unavailable. CPU fallback is forbidden for M1."
            )

        module_relative_path = validate_sam2_origin(repo)
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        origin = git_value(repo, "remote", "get-url", "origin")
        commit = git_value(repo, "rev-parse", "HEAD")
        image, box = synthetic_image(args.image_size)
        Image.fromarray(image, mode="RGB").save(output / "input.png")

        device_index = torch.cuda.current_device()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device_index)
        torch.cuda.synchronize(device_index)

        load_started = time.perf_counter()
        model = build_sam2(
            args.config,
            str(checkpoint),
            device=args.device,
            apply_postprocessing=False,
        )
        predictor = SAM2ImagePredictor(model)
        torch.cuda.synchronize(device_index)
        load_seconds = time.perf_counter() - load_started

        with inference_context(torch, args.dtype):
            torch.cuda.synchronize(device_index)
            embedding_started = time.perf_counter()
            predictor.set_image(image)
            torch.cuda.synchronize(device_index)
            embedding_seconds = time.perf_counter() - embedding_started

            box_array = np.asarray(box, dtype=np.float32)
            torch.cuda.synchronize(device_index)
            predict_started = time.perf_counter()
            masks, scores, _ = predictor.predict(
                point_coords=None,
                point_labels=None,
                box=box_array,
                multimask_output=True,
            )
            torch.cuda.synchronize(device_index)
            predict_seconds = time.perf_counter() - predict_started

        best_index = int(np.argmax(scores))
        best_mask = np.asarray(masks[best_index], dtype=bool)
        best_score = float(scores[best_index])
        mask_image = (best_mask.astype(np.uint8) * 255)
        Image.fromarray(mask_image, mode="L").save(output / "mask.png")

        overlay = image.astype(np.float32)
        red = np.zeros_like(overlay)
        red[..., 0] = 255
        overlay[best_mask] = overlay[best_mask] * 0.55 + red[best_mask] * 0.45
        Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8), mode="RGB").save(
            output / "overlay.png"
        )

        properties = torch.cuda.get_device_properties(device_index)
        metadata.update(
            {
                "status": "success",
                "torch": torch.__version__,
                "torchvision": torchvision.__version__,
                "pytorch_wheel_cuda": torch.version.cuda,
                "cuda_available": torch.cuda.is_available(),
                "gpu": torch.cuda.get_device_name(device_index),
                "vram_total_bytes": properties.total_memory,
                "vram_peak_allocated_bytes": torch.cuda.max_memory_allocated(
                    device_index
                ),
                "vram_peak_reserved_bytes": torch.cuda.max_memory_reserved(
                    device_index
                ),
                "sam2_origin": origin,
                "sam2_commit": commit,
                "sam2_module_relative_path": module_relative_path,
                "checkpoint_sha256": sha256_file(checkpoint),
                "checkpoint_bytes": checkpoint.stat().st_size,
                "bounding_box_xyxy": box,
                "multimask_output": True,
                "selected_mask_index": best_index,
                "mask_score": best_score,
                "mask_foreground_pixels": int(best_mask.sum()),
                "load_seconds": load_seconds,
                "set_image_seconds": embedding_seconds,
                "predict_seconds": predict_seconds,
                "bf16_supported": torch.cuda.is_bf16_supported(),
                "output_files": [
                    "input.png",
                    "mask.png",
                    "overlay.png",
                    "metadata.json",
                ],
            }
        )
        write_json(metadata_path, metadata)
        print(json.dumps(metadata, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        metadata["error_type"] = classify_error(exc)
        metadata["error_class"] = type(exc).__name__
        metadata["error_message"] = str(exc)

        try:
            import torch

            metadata["torch"] = torch.__version__
            metadata["pytorch_wheel_cuda"] = torch.version.cuda
            metadata["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                device_index = torch.cuda.current_device()
                properties = torch.cuda.get_device_properties(device_index)
                metadata["gpu"] = torch.cuda.get_device_name(device_index)
                metadata["vram_total_bytes"] = properties.total_memory
                metadata["vram_allocated_bytes"] = torch.cuda.memory_allocated(
                    device_index
                )
                metadata["vram_reserved_bytes"] = torch.cuda.memory_reserved(
                    device_index
                )
                metadata["vram_peak_allocated_bytes"] = (
                    torch.cuda.max_memory_allocated(device_index)
                )
        except Exception:
            pass

        try:
            output.mkdir(parents=True, exist_ok=True)
            write_json(metadata_path, metadata)
        except OSError:
            pass
        print(
            f"Feasibility run failed [{metadata['error_type']}]: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

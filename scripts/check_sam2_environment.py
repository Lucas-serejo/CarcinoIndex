"""Validate the isolated SAM 2.1 feasibility environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import platform
import subprocess
import sys
from pathlib import Path
from typing import Sequence


DEFAULT_CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"


class ValidationError(RuntimeError):
    """Raised when a required feasibility condition is not satisfied."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Python, CUDA, SAM 2, config, and checkpoint readiness."
    )
    parser.add_argument("--sam2-repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    return parser.parse_args(argv)


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def pip_version() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
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


def require_module_from_repo(repo: Path) -> Path:
    spec = importlib.util.find_spec("sam2")
    if spec is None or spec.origin is None:
        raise ValidationError("The sam2 package is not importable.")
    module_path = Path(spec.origin).resolve()
    try:
        module_path.relative_to(repo.resolve())
    except ValueError as exc:
        raise ValidationError(
            "sam2 resolves outside the approved official clone: "
            f"{module_path}"
        ) from exc
    return module_path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.sam2_repo.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    config = resolve_config(repo, args.config)

    try:
        if not repo.is_dir():
            raise ValidationError(f"SAM 2 repository not found: {repo}")
        if not checkpoint.is_file():
            raise ValidationError(f"Checkpoint not found: {checkpoint}")
        if not config.is_file():
            raise ValidationError(f"Config not found: {config}")

        try:
            import torch
            import torchvision
        except ImportError as exc:
            raise ValidationError(f"PyTorch import failed: {exc}") from exc

        if not torch.cuda.is_available():
            raise ValidationError(
                "CUDA is unavailable. CPU fallback is forbidden for M1."
            )

        module_path = require_module_from_repo(repo)
        device = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(device)

        print(f"Operating system: {platform.platform()}")
        print(f"Python: {platform.python_version()}")
        print(f"Python executable: {sys.executable}")
        print(f"Virtual environment active: {sys.prefix != sys.base_prefix}")
        print(f"pip: {pip_version()}")
        print(f"torch: {torch.__version__}")
        print(f"torchvision: {torchvision.__version__}")
        print(f"PyTorch wheel CUDA: {torch.version.cuda}")
        print(f"CUDA available: {torch.cuda.is_available()}")
        print(f"GPU: {torch.cuda.get_device_name(device)}")
        print(f"VRAM total bytes: {properties.total_memory}")
        print(f"VRAM allocated bytes: {torch.cuda.memory_allocated(device)}")
        print(f"VRAM reserved bytes: {torch.cuda.memory_reserved(device)}")
        print(f"BF16 supported: {torch.cuda.is_bf16_supported()}")
        print(f"sam2 package version: {package_version('SAM-2')}")
        print(f"sam2 module: {module_path}")
        print(f"Checkpoint exists: {checkpoint.is_file()}")
        print(f"Checkpoint bytes: {checkpoint.stat().st_size}")
        print(f"Config logical name: {args.config}")
        print(f"Config exists: {config.is_file()}")
        print("SAM2 CUDA extension requested: no (SAM2_BUILD_CUDA=0)")
        print("Environment validation: OK")
        return 0
    except (OSError, subprocess.SubprocessError, ValidationError) as exc:
        print(f"Environment validation: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

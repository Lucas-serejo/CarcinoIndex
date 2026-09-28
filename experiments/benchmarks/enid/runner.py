"""Sequential runner reusing SAM2Segmenter and its selected_mask unchanged."""

from __future__ import annotations

import csv
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean, median

import numpy as np
from PIL import Image

from backend.ai.segmentation.sam_segmenter import (
    DEFAULT_MODEL_CONFIG, MODEL_NAME, SAM2Segmenter, SegmentationResult,
)
from .dataset import SPLITS, load_samples, overlap_metrics, reference_mask, xywh_to_xyxy

FIELDS = (
    "dataset", "split", "group_id", "image_id", "annotation_id", "file_name",
    "width", "height", "bbox_x", "bbox_y", "bbox_width", "bbox_height",
    "polygon_count", "reference_area_pixels", "predicted_area_pixels", "dice",
    "iou", "selected_index", "selected_score", "prediction_time_seconds",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _statistics(rows: list[dict]) -> dict:
    return {metric: {"mean": mean(row[metric] for row in rows) if rows else None,
                     "median": median(row[metric] for row in rows) if rows else None}
            for metric in ("dice", "iou")}


def _versions() -> dict:
    versions = {}
    for package in ("numpy", "Pillow", "pycocotools", "torch", "SAM-2"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


def run_benchmark(*, dataset_root: Path, split_root: Path, checkpoint: Path,
                  output: Path, split: str = "all", limit: int | None = None,
                  device: str = "cuda", dtype: str = "float32",
                  model_config: str = DEFAULT_MODEL_CONFIG,
                  segmenter_factory=SAM2Segmenter) -> dict:
    started = time.perf_counter()
    # Never let an output argument write into the read-only experimental inputs.
    raw_root = Path(__file__).resolve().parents[3] / "datasets" / "raw"
    for protected in (dataset_root, split_root, raw_root):
        if output.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Output must be outside dataset and split directories.")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty; use a new run directory.")
    rows, processed_images = [], set()
    summary = {
        "status": "incomplete", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "ENID", "requested_split": split, "limit": limit,
        "model": MODEL_NAME, "model_config": Path(model_config).name if Path(model_config).is_absolute() else model_config,
        "checkpoint_filename": checkpoint.name, "device": device, "dtype": dtype,
        "multimask_output": True, "selection_policy": "highest SAM predicted score",
        "metrics": ["Dice", "IoU"], "package_versions": _versions(),
        "success_count": 0, "failure_count": 0, "selected_annotations": None,
    }
    current_annotation = None
    current_image = None
    stage = "validation"
    partial = output / "results.incomplete.csv"

    def save_summary():
        summary.update(
            annotations_processed=len(rows), images_processed=len(processed_images),
            success_count=len(rows), overall=_statistics(rows),
            by_split={name: {"count": sum(row["split"] == name for row in rows),
                             **_statistics([row for row in rows if row["split"] == name])}
                      for name in SPLITS if any(row["split"] == name for row in rows)},
            total_time_seconds=time.perf_counter() - started,
        )
        temporary = output / "summary.tmp"
        temporary.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output / "summary.json")

    save_summary()
    try:
        with partial.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            if not checkpoint.is_file():
                raise ValueError("Checkpoint not found; supply an existing local checkpoint.")
            samples = load_samples(dataset_root, split_root, split, limit)
            summary.update(
                selected_annotations=len(samples),
                coco_sha256=sha256_file(dataset_root / "coco.json"),
                split_sha256={name: sha256_file(split_root / f"coco_{name}.json") for name in SPLITS},
                checkpoint_sha256=sha256_file(checkpoint),
            )
            save_summary()
            grouped = defaultdict(list)
            for sample in samples:
                grouped[sample.image_id].append(sample)
            segmenter = segmenter_factory(checkpoint_path=checkpoint, model_config=model_config,
                                          device=device, dtype=dtype)
            try:
                stage = "model_load"
                segmenter.load()
                for current_image, image_samples in grouped.items():
                    sample = image_samples[0]
                    current_annotation = None
                    stage = "image_load"
                    try:
                        with Image.open(dataset_root / "frames" / sample.file_name) as source:
                            if source.size != (sample.width, sample.height):
                                raise ValueError("Frame dimensions disagree with canonical COCO.")
                            rgb = np.array(source.convert("RGB"), dtype=np.uint8)
                        stage = "image_embedding"
                        segmenter.set_image(rgb)
                        for sample in image_samples:
                            current_annotation = sample.annotation_id
                            stage = "annotation"
                            reference = reference_mask(sample)
                            result: SegmentationResult = segmenter.segment_with_box(
                                xywh_to_xyxy(sample.bbox_xywh), multimask_output=True,
                            )
                            metrics = overlap_metrics(result.selected_mask, reference)
                            if not np.isfinite([result.selected_score, result.prediction_time_seconds]).all():
                                raise ValueError("SAM returned non-finite score or prediction time.")
                            row = dict(
                                dataset="ENID", split=sample.split, group_id=sample.group_id,
                                image_id=sample.image_id, annotation_id=sample.annotation_id,
                                file_name=sample.file_name, width=sample.width, height=sample.height,
                                **dict(zip(("bbox_x", "bbox_y", "bbox_width", "bbox_height"), sample.bbox_xywh)),
                                polygon_count=len(sample.segmentation), **metrics,
                                selected_index=int(result.selected_index), selected_score=float(result.selected_score),
                                prediction_time_seconds=float(result.prediction_time_seconds),
                            )
                            writer.writerow(row)
                            stream.flush()
                            rows.append(row)
                            processed_images.add(current_image)
                        save_summary()
                    finally:
                        segmenter.clear_image()
            finally:
                segmenter.close()
        stage = "output"
        partial.replace(output / "results.csv")
        summary["status"] = "complete"
        save_summary()
    except BaseException as exc:
        summary.update(status="incomplete", failure_count=1,
                       failure={"stage": stage, "image_id": current_image,
                                "annotation_id": current_annotation, "error_type": type(exc).__name__})
        # Persist identifiers, not exception text which can contain absolute paths.
        save_summary()
        raise RuntimeError(
            f"ENID benchmark incomplete at {stage} (image={current_image}, "
            f"annotation={current_annotation}): {exc}"
        ) from exc
    return summary

"""SAM robustness to imprecise boxes: original, expanded and jittered prompts per annotation."""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean, median

import numpy as np
import pycocotools
from PIL import Image

from backend.ai.segmentation.sam_segmenter import (
    DEFAULT_MODEL_CONFIG, MODEL_NAME, SAM2Segmenter, SegmentationResult,
)
from experiments.analysis.enid.box_baseline import box_mask
from .dataset import SPLITS, Sample, load_samples, overlap_metrics, reference_mask, xywh_to_xyxy
from .runner import sha256_file

SEED = 20261027


@dataclass(frozen=True)
class Condition:
    """mode: original (bbox as is), expand (each side outward by fraction of
    bbox width/height) or jitter (each coordinate shifted by U[-fraction,
    +fraction] of bbox width/height, independently)."""
    name: str
    multimask_output: bool
    mode: str
    fraction: float = 0.0


CONDITIONS = (
    Condition("ref", True, "original"),
    Condition("ref_single", False, "original"),
    Condition("expand10", True, "expand", 0.10),
    Condition("expand20", True, "expand", 0.20),
    Condition("jitter10", True, "jitter", 0.10),
)
FIELDS = (
    "split", "group_id", "image_id", "annotation_id", "condition",
    "prompt_x_min", "prompt_y_min", "prompt_x_max", "prompt_y_max", "clipped",
    "reference_area_pixels", "predicted_area_pixels", "dice", "iou",
    "selected_index", "selected_score", "prediction_time_seconds",
    "prompt_box_area_pixels", "prompt_box_dice", "prompt_box_iou",
)
TIMING_FIELDS = ("image_id", "width", "height", "embedding_time_seconds")


def perturb_box(bbox_xywh: tuple[float, ...], width: int, height: int, condition: Condition,
                annotation_id: int, seed: int = SEED) -> tuple[tuple[float, ...], bool]:
    """Return the XYXY prompt clipped to the image and whether clipping occurred.

    Jitter uses numpy.random.default_rng([seed, annotation_id]) and draws
    uniform(-fraction, fraction, 4) in x_min, y_min, x_max, y_max order, so a
    prompt depends only on the seed and annotation ID, never on run order.
    Inverted or empty boxes raise instead of being corrected.
    """
    x, y, w, h = bbox_xywh
    if condition.mode == "original":
        return tuple(float(v) for v in xywh_to_xyxy(bbox_xywh)), False
    if condition.mode == "expand":
        f = condition.fraction
        box = (x - f * w, y - f * h, x + w + f * w, y + h + f * h)
    elif condition.mode == "jitter":
        dx0, dy0, dx1, dy1 = np.random.default_rng([seed, annotation_id]).uniform(
            -condition.fraction, condition.fraction, 4)
        box = (x + dx0 * w, y + dy0 * h, x + w + dx1 * w, y + h + dy1 * h)
    else:
        raise ValueError(f"Unknown condition mode: {condition.mode}")
    clipped_box = (max(box[0], 0.0), max(box[1], 0.0), min(box[2], width), min(box[3], height))
    for candidate in (box, clipped_box):
        if not (candidate[2] > candidate[0] and candidate[3] > candidate[1]):
            raise ValueError(f"Degenerate {condition.name} box for annotation {annotation_id}: {candidate}")
    return tuple(float(v) for v in clipped_box), clipped_box != box


def prompt_box_mask(sample: Sample, box_xyxy: tuple[float, ...], original: bool) -> np.ndarray:
    """Rasterize a prompt with box_baseline.box_mask (single rectangle-polygon convention)."""
    if original:
        return box_mask(sample)
    x0, y0, x1, y1 = box_xyxy
    return box_mask(replace(sample, bbox_xywh=(x0, y0, x1 - x0, y1 - y0)))


def _versions() -> dict:
    versions = {}
    for package in ("numpy", "Pillow", "pycocotools", "torch", "SAM-2"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    versions["pycocotools_file"] = pycocotools.__file__
    versions["python"] = sys.version.split()[0]
    return versions


def _gpu(device: str) -> dict | None:
    if not str(device).startswith("cuda"):
        return None
    import torch
    index = torch.device(device).index or 0
    return {"name": torch.cuda.get_device_name(index), "torch_cuda": torch.version.cuda,
            "total_memory_bytes": torch.cuda.get_device_properties(index).total_memory}


def _by_condition(rows: list[dict], conditions) -> dict:
    result = {}
    for condition in conditions:
        subset = [row for row in rows if row["condition"] == condition.name]
        if not subset:
            continue
        beats = sum(row["dice"] > row["prompt_box_dice"] for row in subset)
        result[condition.name] = {
            "count": len(subset),
            "dice": {"mean": mean(r["dice"] for r in subset), "median": median(r["dice"] for r in subset)},
            "iou": {"mean": mean(r["iou"] for r in subset), "median": median(r["iou"] for r in subset)},
            "prompt_box_dice_mean": mean(r["prompt_box_dice"] for r in subset),
            "prompt_box_iou_mean": mean(r["prompt_box_iou"] for r in subset),
            "sam_beats_prompt_box": {"count": beats, "percentage": beats / len(subset) * 100},
            "clipped_count": sum(r["clipped"] for r in subset),
        }
    return result


def run_robustness(*, dataset_root: Path, split_root: Path, checkpoint: Path, output: Path,
                   split: str = "all", limit: int | None = None, device: str = "cuda",
                   dtype: str = "float32", model_config: str = DEFAULT_MODEL_CONFIG,
                   conditions=CONDITIONS, seed: int = SEED, expected_checkpoint_sha256: str | None = None,
                   segmenter_factory=SAM2Segmenter) -> dict:
    started = time.perf_counter()
    raw_root = Path(__file__).resolve().parents[3] / "datasets" / "raw"
    for protected in (dataset_root, split_root, raw_root):
        if output.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Output must be outside dataset and split directories.")
    names = [condition.name for condition in conditions]
    if not names or len(set(names)) != len(names):
        raise ValueError("Conditions must be nonempty with unique names.")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty; use a new run directory.")
    rows, timings = [], []
    summary = {
        "status": "incomplete", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "ENID", "experiment": "box prompt robustness", "requested_split": split,
        "limit": limit, "model": MODEL_NAME,
        "model_config": Path(model_config).name if Path(model_config).is_absolute() else model_config,
        "checkpoint_filename": checkpoint.name, "device": device, "dtype": dtype,
        "selection_policy": "highest SAM predicted score (index 0 when multimask_output=False)",
        "seed": seed, "conditions": [asdict(condition) for condition in conditions],
        "condition_definitions": {
            "original": "reference bbox converted XYWH -> XYXY, unchanged",
            "expand": "x_min - f*w, y_min - f*h, x_max + f*w, y_max + f*h; then clipped",
            "jitter": "x_min + u0*w, y_min + u1*h, x_max + u2*w, y_max + u3*h; "
                      "u ~ U[-f, f] from numpy.random.default_rng([seed, annotation_id]); then clipped",
            "clipping": "to [0, width] x [0, height]; clipped=True when any coordinate changed",
            "degenerate": "x_max <= x_min or y_max <= y_min before or after clipping raises",
            "coordinates": "float, unrounded; w, h from the original bbox",
            "prompt_box_metrics": "prompt XYXY rasterized via box_baseline.box_mask "
                                  "(rectangle polygon, pycocotools frPyObjects -> merge -> decode) vs reference",
            "order": "per image one set_image; per annotation all conditions in listed order",
        },
        "package_versions": _versions(), "gpu": _gpu(device),
        "success_count": 0, "failure_count": 0, "selected_annotations": None,
    }
    current_annotation = current_image = current_condition = None
    stage = "validation"
    partial = output / "results_long.incomplete.csv"
    partial_timing = output / "image_timing.incomplete.csv"

    def save_summary():
        summary.update(rows_written=len(rows), images_processed=len(timings),
                       success_count=len(rows), by_condition=_by_condition(rows, conditions),
                       total_time_seconds=time.perf_counter() - started)
        temporary = output / "summary.tmp"
        temporary.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output / "summary.json")

    save_summary()
    try:
        with partial.open("w", newline="", encoding="utf-8") as stream, \
                partial_timing.open("w", newline="", encoding="utf-8") as timing_stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            timing_writer = csv.DictWriter(timing_stream, fieldnames=TIMING_FIELDS)
            writer.writeheader()
            timing_writer.writeheader()
            if not checkpoint.is_file():
                raise ValueError("Checkpoint not found; supply an existing local checkpoint.")
            checkpoint_sha256 = sha256_file(checkpoint)
            if expected_checkpoint_sha256 and checkpoint_sha256 != expected_checkpoint_sha256.lower():
                raise ValueError("Checkpoint SHA-256 does not match the expected value.")
            samples = load_samples(dataset_root, split_root, split, limit)
            summary.update(
                selected_annotations=len(samples), expected_rows=len(samples) * len(conditions),
                coco_sha256=sha256_file(dataset_root / "coco.json"),
                split_sha256={name: sha256_file(split_root / f"coco_{name}.json") for name in SPLITS},
                checkpoint_sha256=checkpoint_sha256,
            )
            stage = "prompt_validation"
            # Every prompt is checked before the model loads, so degenerate boxes fail early.
            prompts = {(s.annotation_id, c.name): perturb_box(s.bbox_xywh, s.width, s.height, c,
                                                               s.annotation_id, seed)
                       for s in samples for c in conditions}
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
                    current_annotation = current_condition = None
                    stage = "image_load"
                    try:
                        with Image.open(dataset_root / "frames" / sample.file_name) as source:
                            if source.size != (sample.width, sample.height):
                                raise ValueError("Frame dimensions disagree with canonical COCO.")
                            rgb = np.array(source.convert("RGB"), dtype=np.uint8)
                        stage = "image_embedding"
                        segmenter.set_image(rgb)
                        embedding = segmenter.embedding_time_seconds
                        if embedding is None or not np.isfinite(embedding):
                            raise ValueError("Segmenter did not report a finite embedding time.")
                        image_rows = []
                        for sample in image_samples:
                            current_annotation = sample.annotation_id
                            stage = "annotation"
                            reference = reference_mask(sample)
                            for condition in conditions:
                                current_condition = condition.name
                                box, clipped = prompts[(sample.annotation_id, condition.name)]
                                result: SegmentationResult = segmenter.segment_with_box(
                                    box, multimask_output=condition.multimask_output)
                                if not np.isfinite([result.selected_score, result.prediction_time_seconds]).all():
                                    raise ValueError("SAM returned non-finite score or prediction time.")
                                metrics = overlap_metrics(result.selected_mask, reference)
                                box_metrics = overlap_metrics(
                                    prompt_box_mask(sample, box, condition.mode == "original"), reference)
                                image_rows.append(dict(
                                    split=sample.split, group_id=sample.group_id, image_id=sample.image_id,
                                    annotation_id=sample.annotation_id, condition=condition.name,
                                    **dict(zip(("prompt_x_min", "prompt_y_min", "prompt_x_max",
                                                "prompt_y_max"), box)),
                                    clipped=clipped, **metrics,
                                    selected_index=int(result.selected_index),
                                    selected_score=float(result.selected_score),
                                    prediction_time_seconds=float(result.prediction_time_seconds),
                                    prompt_box_area_pixels=box_metrics["predicted_area_pixels"],
                                    prompt_box_dice=box_metrics["dice"], prompt_box_iou=box_metrics["iou"],
                                ))
                        # Rows and timing for an image are written together, after all its prompts succeed.
                        writer.writerows(image_rows)
                        timing_writer.writerow(dict(image_id=sample.image_id, width=sample.width,
                                                    height=sample.height,
                                                    embedding_time_seconds=float(embedding)))
                        stream.flush()
                        timing_stream.flush()
                        rows.extend(image_rows)
                        timings.append(embedding)
                        save_summary()
                    finally:
                        segmenter.clear_image()
            finally:
                segmenter.close()
        stage = "output"
        partial.replace(output / "results_long.csv")
        partial_timing.replace(output / "image_timing.csv")
        summary["status"] = "complete"
        save_summary()
    except BaseException as exc:
        summary.update(status="incomplete", failure_count=1,
                       failure={"stage": stage, "image_id": current_image,
                                "annotation_id": current_annotation, "condition": current_condition,
                                "error_type": type(exc).__name__})
        save_summary()
        raise RuntimeError(
            f"ENID robustness incomplete at {stage} (image={current_image}, "
            f"annotation={current_annotation}, condition={current_condition}): {exc}"
        ) from exc
    return summary

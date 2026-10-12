"""Recreate selected Experiment A masks for descriptive visual inspection."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path, PureWindowsPath

import numpy as np
from PIL import Image

from backend.ai.segmentation.sam_segmenter import DEFAULT_MODEL_CONFIG, MODEL_NAME, SAM2Segmenter
from experiments.benchmarks.enid.dataset import (
    SPLITS, load_samples, overlap_metrics, reference_mask, xywh_to_xyxy,
)
from experiments.benchmarks.enid.runner import sha256_file
from .analysis import extreme_cases, load_results

from .selection import TOLERANCE, REASONS, IDENTITY, load_cases
from .rendering import COLORS, ALPHA, _comparison


def render_cases(*, dataset_root: Path, split_root: Path, results: Path, cases: Path,
                 checkpoint: Path, output: Path, device="cuda", dtype="float32",
                 model_config=DEFAULT_MODEL_CONFIG, segmenter_factory=SAM2Segmenter):
    for protected in (dataset_root, split_root,
                      Path(__file__).resolve().parents[3] / "datasets" / "raw"):
        if output.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Output must be outside dataset and split directories.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty; use a new run directory.")
    # Parse the same CSV bytes recorded in provenance.
    result_bytes, case_bytes = results.read_bytes(), cases.read_bytes()
    benchmark = load_results(BytesIO(result_bytes))
    selection_count, selections = load_cases(BytesIO(case_bytes), benchmark)
    canonical = {s.annotation_id: s for s in load_samples(dataset_root, split_root, split="all")}
    records = benchmark.set_index("annotation_id").to_dict("index")
    for aid in selections:
        if aid not in canonical:
            raise ValueError(f"Selected annotation {aid} missing from canonical COCO.")
        sample, record = canonical[aid], records[aid]
        if any(getattr(sample, k) != record[k] for k in (*IDENTITY, "width", "height")):
            raise ValueError(f"Canonical identity disagrees with results for annotation {aid}.")
    import hashlib
    hashes = {"results.csv": hashlib.sha256(result_bytes).hexdigest(),
              "extreme_cases.csv": hashlib.sha256(case_bytes).hexdigest(),
              "coco.json": sha256_file(dataset_root / "coco.json"),
              **{f"coco_{s}.json": sha256_file(split_root / f"coco_{s}.json") for s in SPLITS},
              "checkpoint": sha256_file(checkpoint)}
    versions = {}
    for package in ("numpy", "pandas", "matplotlib", "Pillow", "pycocotools", "torch", "SAM-2"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    manifest = dict(status="incomplete", timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    selection_rows=selection_count, unique_annotations_rendered=0,
                    selected_annotation_ids=list(selections), model=MODEL_NAME,
                    model_config=PureWindowsPath(model_config).name if
                    (Path(model_config).is_absolute() or PureWindowsPath(model_config).is_absolute())
                    else model_config, checkpoint_filename=checkpoint.name, device=device, dtype=dtype,
                    multimask_output=True, selection_policy="highest SAM predicted score",
                    rerun_metric_tolerance=TOLERANCE, package_versions=versions, sha256=hashes)
    output.mkdir(parents=True, exist_ok=True)

    def save_manifest():
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    save_manifest()
    rows, predictions = [], {}
    segmenter = None
    try:
        segmenter = segmenter_factory(checkpoint_path=checkpoint, model_config=model_config,
                                      device=device, dtype=dtype)
        segmenter.load()
        # First-seen image order; ascending annotation order within each image.
        # Cache selected results so rendering/CSV processing stays globally ID-sorted,
        # even when annotations for an image are interleaved in canonical ID order.
        for aid, pairs in selections.items():
            sample, record = canonical[aid], records[aid]
            with Image.open(dataset_root / "frames" / sample.file_name) as source:
                if source.size != (sample.width, sample.height):
                    raise ValueError("Frame dimensions disagree with canonical COCO.")
                rgb = np.array(source.convert("RGB"), dtype=np.uint8)
            if aid not in predictions:
                try:
                    segmenter.set_image(rgb)
                    for other in selections:
                        if canonical[other].image_id == sample.image_id:
                            result = segmenter.segment_with_box(
                                xywh_to_xyxy(canonical[other].bbox_xywh), multimask_output=True)
                            predictions[other] = (result.selected_mask.copy(),
                                                  int(result.selected_index), float(result.selected_score))
                finally:
                    segmenter.clear_image()
            prediction, index, score = predictions.pop(aid)
            reference = reference_mask(sample)
            metrics = overlap_metrics(prediction, reference)
            if not np.isfinite(score):
                raise ValueError(f"Non-finite rerun selected score for annotation {aid}.")
            row = dict(annotation_id=aid, **{k: record[k] for k in IDENTITY},
                       selection_reasons=json.dumps([p[0] for p in pairs]),
                       selection_ranks=json.dumps([p[1] for p in pairs]),
                       **dict(zip(("bbox_x", "bbox_y", "bbox_width", "bbox_height"), sample.bbox_xywh)),
                       reference_area_pixels=record["reference_area_pixels"],
                       benchmark_predicted_area_pixels=record["predicted_area_pixels"],
                       rerun_predicted_area_pixels=int(prediction.sum()),
                       predicted_area_pixel_delta=abs(int(prediction.sum()) - record["predicted_area_pixels"]))
            for key, value in (("dice", metrics["dice"]), ("iou", metrics["iou"]),
                               ("selected_index", index), ("selected_score", score)):
                row[f"benchmark_{key}"] = record[key]
                row[f"rerun_{key}"] = value
                if key != "selected_index":
                    row[f"{key}_abs_delta"] = abs(record[key] - value)
            if (row["dice_abs_delta"] > TOLERANCE or row["iou_abs_delta"] > TOLERANCE
                    or index != record["selected_index"] or row["predicted_area_pixel_delta"] != 0):
                raise ValueError(f"Rerun consistency mismatch for annotation {aid}.")
            if metrics["reference_area_pixels"] != record["reference_area_pixels"]:
                raise ValueError(f"Canonical reference area mismatch for annotation {aid}.")
            directory = output / "cases" / f"annotation_{aid:06d}"
            directory.mkdir(parents=True)
            for name, mask in (("reference_mask", reference), ("sam_mask", prediction)):
                path = directory / f"{name}.png"
                Image.fromarray(mask.astype(np.uint8) * 255).save(path)
                row[f"{name}_path"] = path.relative_to(output).as_posix()
            path = directory / "comparison.png"
            _comparison(path, rgb, reference, prediction, sample, record)
            row["comparison_path"] = path.relative_to(output).as_posix()
            rows.append(row)
            manifest["unique_annotations_rendered"] = len(rows)
        with (output / "cases.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        manifest["status"] = "complete"
    except BaseException as exc:
        manifest["failure"] = {"error_type": type(exc).__name__}
        raise
    finally:
        try:
            if segmenter is not None:
                segmenter.close()
        finally:
            save_manifest()
    return manifest

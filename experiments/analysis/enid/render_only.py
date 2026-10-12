"""Verify completed qualitative artifacts and render them without importing SAM."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path

import numpy as np
from PIL import Image

from experiments.benchmarks.enid.dataset import SPLITS, load_samples, reference_mask, overlap_metrics
from .analysis import load_results
from .localization import validate_language
from .rendering import _comparison
from .selection import IDENTITY, TOLERANCE, load_cases


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(row, key):
    value = float(row[key])
    _require(np.isfinite(value), f"Non-finite {key}.")
    return value


def _source_path(root, relative):
    path = (root / relative).resolve()
    _require(path.is_relative_to(root.resolve()) and path != root.resolve(), "Artifact path escapes source directory.")
    return path


def render_existing(*, dataset_root: Path, split_root: Path, results: Path, cases: Path,
                    source: Path, output: Path, language="pt-BR"):
    """Read all inputs and validate every case before creating a new output directory.

    Works for synthetic subsets too; production selection must match all 16 IDs
    recorded by the completed source run and deterministic extreme_cases().
    """
    validate_language(language)
    dataset_root, split_root, results, cases, source, output = map(
        Path, (dataset_root, split_root, results, cases, source, output))
    for protected in (source, dataset_root, split_root,
                      Path(__file__).resolve().parents[3] / "datasets" / "raw"):
        _require(not output.resolve().is_relative_to(protected.resolve()), "Output must be outside source directories.")
    _require(not output.exists(), "Output must be a new directory.")
    inputs = {"results.csv": results.read_bytes(), "extreme_cases.csv": cases.read_bytes(),
              "source/cases.csv": (source / "cases.csv").read_bytes(),
              "source/manifest.json": (source / "manifest.json").read_bytes(),
              "coco.json": (dataset_root / "coco.json").read_bytes(),
              **{f"coco_{s}.json": (split_root / f"coco_{s}.json").read_bytes() for s in SPLITS}}
    hashes = {name: _digest(data) for name, data in inputs.items()}
    manifest = json.loads(inputs["source/manifest.json"])
    _require(manifest.get("status") == "complete", "Source manifest must be complete.")
    _require(manifest.get("selection_policy") == "highest SAM predicted score" and
             manifest.get("multimask_output") is True and
             manifest.get("rerun_metric_tolerance") == TOLERANCE, "Source protocol mismatch.")
    for name in ("results.csv", "extreme_cases.csv", "coco.json", *[f"coco_{s}.json" for s in SPLITS]):
        _require(manifest.get("sha256", {}).get(name) == hashes[name], f"Source hash mismatch: {name}.")
    frame = load_results(BytesIO(inputs["results.csv"]))
    selection_count, selections = load_cases(BytesIO(inputs["extreme_cases.csv"]), frame)
    ids = list(selections)
    _require(manifest.get("selected_annotation_ids") == ids and
             manifest.get("unique_annotations_rendered") == len(ids) and
             manifest.get("selection_rows") == selection_count, "Source selection mismatch.")
    rows = list(csv.DictReader(StringIO(inputs["source/cases.csv"].decode("utf-8"))))
    _require([int(r["annotation_id"]) for r in rows] == ids, "Cases IDs/order must match deterministic selection.")
    canonical = {s.annotation_id: s for s in load_samples(dataset_root, split_root, split="all")}
    # Guard against a source change between hashing and COCO parsing.
    _require((dataset_root / "coco.json").read_bytes() == inputs["coco.json"] and all(
        (split_root / f"coco_{s}.json").read_bytes() == inputs[f"coco_{s}.json"] for s in SPLITS),
        "COCO inputs changed during validation.")
    records = frame.set_index("annotation_id").to_dict("index")
    verified = []
    mask_hashes, image_hashes = {}, {}
    for row, aid in zip(rows, ids):
        _require(aid in canonical, f"Missing canonical annotation {aid}.")
        sample, record = canonical[aid], records[aid]
        _require(all(getattr(sample, k) == record[k] for k in (*IDENTITY, "width", "height")), "Canonical identity mismatch.")
        _require(_number(row, "image_id") == record["image_id"] and all(
            row[k] == record[k] for k in IDENTITY if k != "image_id"), "Cases identity mismatch.")
        _require(json.loads(row["selection_reasons"]) == [p[0] for p in selections[aid]] and
                 json.loads(row["selection_ranks"]) == [p[1] for p in selections[aid]], "Cases selection mismatch.")
        for key, value in zip(("bbox_x", "bbox_y", "bbox_width", "bbox_height"), sample.bbox_xywh):
            _require(_number(row, key) == value and (key not in record or _number(record, key) == value), "Canonical bbox mismatch.")
        for key in ("dice", "iou", "selected_index", "selected_score"):
            _require(_number(row, f"benchmark_{key}") == record[key], f"Benchmark {key} mismatch.")
        _require(_number(row, "rerun_selected_index") == record["selected_index"], "Selected index mismatch.")
        score = _number(row, "rerun_selected_score")
        _require(abs(_number(row, "selected_score_abs_delta") - abs(score - record["selected_score"])) <= 1e-12,
                 "Recorded score delta mismatch.")
        masks = []
        for key in ("reference_mask_path", "sam_mask_path"):
            expected_path = f"cases/annotation_{aid:06d}/{key.removesuffix('_path')}.png"
            _require(row[key] == expected_path, "Mask path does not match annotation identity.")
            data = _source_path(source, row[key]).read_bytes()
            mask_hashes[row[key]] = _digest(data)
            with Image.open(BytesIO(data)) as image:
                _require(image.format == "PNG" and image.mode == "L" and image.size == (sample.width, sample.height),
                         "Mask format/dimensions mismatch.")
                pixels = np.array(image)
            _require(np.isin(pixels, [0, 255]).all(), "Masks must be binary 0/255.")
            masks.append(pixels == 255)
        reference, prediction = masks
        _require(np.array_equal(reference, reference_mask(sample)), "Saved reference differs from canonical COCO.")
        metrics = overlap_metrics(prediction, reference)
        for key in ("dice", "iou"):
            _require(abs(metrics[key] - record[key]) <= TOLERANCE and
                     abs(_number(row, f"rerun_{key}") - metrics[key]) <= TOLERANCE and
                     abs(_number(row, f"{key}_abs_delta") - abs(_number(row, f"rerun_{key}") - record[key])) <= 1e-12,
                     f"Saved-mask {key} consistency mismatch.")
        _require(metrics["reference_area_pixels"] == record["reference_area_pixels"] == _number(row, "reference_area_pixels"),
                 "Reference area mismatch.")
        _require(metrics["predicted_area_pixels"] == record["predicted_area_pixels"] ==
                 _number(row, "benchmark_predicted_area_pixels") == _number(row, "rerun_predicted_area_pixels") and
                 _number(row, "predicted_area_pixel_delta") == 0, "Predicted area mismatch.")
        image_data = _source_path(dataset_root / "frames", sample.file_name).read_bytes()
        image_hashes[sample.file_name] = _digest(image_data)
        with Image.open(BytesIO(image_data)) as image:
            _require(image.size == (sample.width, sample.height), "Original image dimensions mismatch.")
            rgb = np.array(image.convert("RGB"), dtype=np.uint8)
        verified.append((rgb, reference, prediction, sample, record))
    # All validation above is read-only. Keep verified snapshots for rendering.
    output.mkdir(parents=True)
    provenance = dict(status="incomplete", mode="render-only", inference_executed=False,
                      language=language, source_directory=source.resolve().name,
                      timestamp_utc=datetime.now(timezone.utc).isoformat(),
                      selected_annotation_ids=ids, sha256=hashes,
                      source_mask_sha256=mask_hashes, source_image_sha256=image_hashes,
                      metric_tolerance=TOLERANCE, unique_annotations_rendered=0)
    def save_manifest():
        (output / "manifest.json").write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    save_manifest()
    try:
        for rgb, reference, prediction, sample, record in verified:
            directory = output / "cases" / f"annotation_{sample.annotation_id:06d}"
            directory.mkdir(parents=True)
            _comparison(directory / "comparison.png", rgb, reference, prediction, sample, record, language)
            provenance["unique_annotations_rendered"] += 1
        provenance["status"] = "complete"
    finally:
        save_manifest()
    return provenance

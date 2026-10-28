"""Filled reference-bbox baseline and cluster-bootstrap CIs; CPU only, no inference."""

from __future__ import annotations

from .analysis import load_results
from .localization import localize_figure, validate_language

import hashlib
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pycocotools
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Text
from pycocotools import mask as coco_mask

from experiments.benchmarks.enid.dataset import (
    SPLITS, Sample, load_samples, overlap_metrics, reference_mask,
)

SEED = 20261027
N_RESAMPLES = 10000
LEVEL = 0.95
BBOX_COLUMNS = ("bbox_x", "bbox_y", "bbox_width", "bbox_height")
BOOTSTRAP_COLUMNS = ("dice", "iou", "box_dice", "box_iou", "dice_gain", "iou_gain")
BOOTSTRAP_CLUSTERS = ("group_id", "image_id")
BOX_DICE_THRESHOLD = 0.80
TERCILE_LABELS = ("T1 (lowest fill ratio)", "T2", "T3 (highest fill ratio)")
OUTPUT_COLUMNS = (
    "split", "group_id", "image_id", "annotation_id", "file_name", "width", "height",
    *BBOX_COLUMNS, "reference_area_pixels", "box_area_pixels", "reference_pixels_outside_box",
    "fill_ratio", "dice", "iou", "box_dice", "box_iou", "dice_gain", "iou_gain",
)
# Supplements localization.PT_BR for this figure only; applied after localize_figure.
PT_BR_EXTRA = {
    "Dice gain over the filled reference bbox":
        "Ganho de Dice sobre a caixa delimitadora de referência preenchida",
    "Fill ratio (reference area / bbox area)":
        "Razão de preenchimento (área da referência / área da caixa delimitadora)",
    "Dice gain (SAM − filled bbox)": "Ganho de Dice (SAM − caixa delimitadora preenchida)",
    "Positive gain": "Ganho positivo",
    "Exploratory, annotation-level": "Exploratório, por anotação",
}


def box_mask(sample: Sample) -> np.ndarray:
    """Rasterize the XYWH bbox as a rectangle polygon, like reference_mask()."""
    x, y, w, h = sample.bbox_xywh
    polygon = [[x, y, x + w, y, x + w, y + h, x, y + h]]
    rles = coco_mask.frPyObjects(polygon, sample.height, sample.width)
    result = coco_mask.decode(coco_mask.merge(rles)).astype(bool)
    if not result.any():
        raise ValueError(f"Annotation {sample.annotation_id} bbox rasterizes to an empty mask.")
    return result


def _matching_samples(frame: pd.DataFrame, dataset_root: Path, split_root: Path) -> list[Sample]:
    missing = sorted(set(BBOX_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required bbox columns: {', '.join(missing)}")
    samples = {s.annotation_id: s for s in load_samples(dataset_root, split_root, split="all")}
    unknown = sorted(set(frame.annotation_id) - set(samples))
    if unknown:
        raise ValueError(f"annotation_id not found in canonical COCO: {unknown[:10]}")
    selected = []
    for row in frame.itertuples(index=False):
        sample = samples[row.annotation_id]
        identity = {"image_id": sample.image_id, "group_id": sample.group_id,
                    "file_name": sample.file_name, "width": sample.width,
                    "height": sample.height, "split": sample.split}
        for name, expected in identity.items():
            if getattr(row, name) != expected:
                raise ValueError(f"Annotation {sample.annotation_id}: {name} disagrees with COCO.")
        for name, expected in zip(BBOX_COLUMNS, sample.bbox_xywh):
            try:
                value = float(getattr(row, name))
            except ValueError as exc:
                raise ValueError(f"Annotation {sample.annotation_id}: {name} must be numeric.") from exc
            if value != expected:
                raise ValueError(f"Annotation {sample.annotation_id}: {name} disagrees with COCO bbox.")
        selected.append(sample)
    return selected


def box_baseline(frame: pd.DataFrame, dataset_root: Path, split_root: Path) -> pd.DataFrame:
    """One row per results.csv annotation; SAM Dice/IoU are consumed as supplied."""
    rows = []
    for row, sample in zip(frame.itertuples(index=False),
                           _matching_samples(frame, dataset_root, split_root)):
        reference, box = reference_mask(sample), box_mask(sample)
        metrics = overlap_metrics(box, reference)
        if metrics["reference_area_pixels"] != row.reference_area_pixels:
            raise ValueError(f"Annotation {sample.annotation_id}: reference area disagrees with results.")
        rows.append({
            **{name: getattr(row, name) for name in OUTPUT_COLUMNS[:7]},
            **dict(zip(BBOX_COLUMNS, sample.bbox_xywh)),
            "reference_area_pixels": metrics["reference_area_pixels"],
            "box_area_pixels": metrics["predicted_area_pixels"],
            "reference_pixels_outside_box": int(np.count_nonzero(reference & ~box)),
            "fill_ratio": metrics["reference_area_pixels"] / metrics["predicted_area_pixels"],
            "dice": row.dice, "iou": row.iou,
            "box_dice": metrics["dice"], "box_iou": metrics["iou"],
            "dice_gain": row.dice - metrics["dice"], "iou_gain": row.iou - metrics["iou"],
        })
    return pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS))


def cluster_bootstrap(frame: pd.DataFrame, columns, cluster: str, n_resamples: int = N_RESAMPLES,
                      seed: int = SEED, level: float = LEVEL, *, keep_replicates: bool = False) -> dict:
    """Percentile CI for annotation-level means, resampling whole clusters with replacement.

    Each replicate draws as many clusters as observed (sorted cluster order,
    numpy.random.default_rng(seed).integers); every row of a drawn cluster
    enters the replicate, so its mean is weighted by annotations. One draw
    matrix is shared by all columns.
    """
    columns = list(columns)
    if cluster not in frame.columns or any(name not in frame.columns for name in columns):
        raise ValueError("cluster and columns must exist in frame.")
    if frame.empty or not columns:
        raise ValueError("cluster_bootstrap requires rows and at least one column.")
    if type(n_resamples) is not int or n_resamples <= 0:
        raise ValueError("n_resamples must be a positive integer.")
    if type(seed) is not int:
        raise ValueError("seed must be an integer.")
    if not 0 < level < 1:
        raise ValueError("level must be in (0, 1).")
    values = frame[columns].astype(float)
    if not np.isfinite(values.to_numpy()).all() or frame[cluster].isna().any():
        raise ValueError("Bootstrap values must be finite and clusters defined.")
    grouped = values.groupby(frame[cluster], sort=True)
    sums, counts = grouped.sum().to_numpy(), grouped.size().to_numpy()
    draws = np.random.default_rng(seed).integers(0, len(counts), size=(n_resamples, len(counts)))
    replicates = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)[:, None]
    alpha = 1 - level
    lower, upper = np.quantile(replicates, [alpha / 2, 1 - alpha / 2], axis=0)
    result = {
        "cluster": cluster, "n_clusters": int(len(counts)), "n_rows": int(len(frame)),
        "n_resamples": n_resamples, "seed": seed, "level": level,
        "method": "percentile", "quantile_method": "linear",
        "rng": "numpy.random.default_rng (PCG64)",
        "statistic": "annotation-weighted mean over resampled clusters",
        "columns": {name: {"mean": float(values[name].mean()), "ci_lower": float(lower[i]),
                           "ci_upper": float(upper[i])} for i, name in enumerate(columns)},
    }
    if keep_replicates:
        result["replicates"] = {name: replicates[:, i] for i, name in enumerate(columns)}
    return result


def _terciles(frame: pd.DataFrame) -> list[dict]:
    # Equal-frequency bins on ranks; ties broken by ascending annotation_id.
    ordered = frame.sort_values("annotation_id")
    labels = pd.qcut(ordered.fill_ratio.rank(method="first"), 3, labels=TERCILE_LABELS)
    rows = []
    for label in TERCILE_LABELS:
        subset = ordered[labels == label]
        rows.append({"tercile": label, "count": int(len(subset)),
                     "fill_ratio_min": float(subset.fill_ratio.min()),
                     "fill_ratio_max": float(subset.fill_ratio.max()),
                     **{f"{name}_median": float(subset[name].median())
                        for name in ("fill_ratio", "dice", "box_dice", "dice_gain")}})
    return rows


def describe(frame: pd.DataFrame) -> dict:
    n, positive = len(frame), int((frame.dice_gain > 0).sum())
    high_box = int((frame.box_dice >= BOX_DICE_THRESHOLD).sum())
    outside = frame.reference_pixels_outside_box
    return {
        "row_count": n, "unique_image_count": int(frame.image_id.nunique()),
        "unique_group_id_count": int(frame.group_id.nunique()),
        **{name: {"mean": float(frame[name].mean()), "median": float(frame[name].median())}
           for name in ("dice", "iou", "box_dice", "box_iou", "dice_gain", "iou_gain", "fill_ratio")},
        "positive_dice_gain": {"count": positive, "percentage": positive / n * 100},
        "box_dice_at_least_0_80": {"count": high_box, "percentage": high_box / n * 100},
        "reference_pixels_outside_box": {
            "total": int(outside.sum()), "annotations_with_any": int((outside > 0).sum()),
            "max": int(outside.max()),
            "total_reference_pixels": int(frame.reference_area_pixels.sum())},
        "fill_ratio_terciles": {"label": "exploratory", "rows": _terciles(frame)},
    }


def _versions() -> dict:
    versions = {}
    for package in ("numpy", "pandas", "pycocotools", "matplotlib"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    versions["pycocotools_file"] = pycocotools.__file__
    versions["python"] = sys.version.split()[0]
    return versions


def _figure(frame: pd.DataFrame, summary: dict, output: Path, language: str) -> None:
    fig = Figure(figsize=(6.4, 4.2), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.scatter(frame.fill_ratio, frame.dice_gain, s=18, color="0.25", alpha=0.65)
    ax.axhline(0, color="black", linestyle="--", linewidth=1)
    ax.set(xlim=(0, 1), xlabel="Fill ratio (reference area / bbox area)",
           ylabel="Dice gain (SAM − filled bbox)", title="Dice gain over the filled reference bbox")
    gain = summary["positive_dice_gain"]
    ax.text(0.03, 0.03, f"Positive gain: {gain['count']}/{summary['row_count']} "
            f"({gain['percentage']:.1f}%)\nExploratory, annotation-level",
            transform=ax.transAxes, fontsize=9, va="bottom",
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
    localize_figure(fig, language)
    if language == "pt-BR":
        for artist in fig.findobj(match=Text):
            value = artist.get_text()
            for source, target in PT_BR_EXTRA.items():
                value = value.replace(source, target)
            artist.set_text(value)
    fig.savefig(output / "dice_gain_vs_fill_ratio.png", dpi=180, metadata={"Software": "CarcinoIndex"})
    fig.clear()


def analyze_box_baseline(*, dataset_root: Path, split_root: Path, results: Path, output: Path,
                         language: str = "en", expected_sha256: str | None = None) -> dict:
    """Read results.csv and canonical COCO; write three artifacts to a new or empty directory."""
    validate_language(language)
    dataset_root, split_root = Path(dataset_root), Path(split_root)
    results, output = Path(results), Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be empty; use a new analysis directory.")
    raw_root = Path(__file__).resolve().parents[3] / "datasets" / "raw"
    for protected in (dataset_root, split_root, raw_root):
        if output.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Output must be outside dataset and split directories.")
    source_bytes = results.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ValueError(f"results SHA-256 {digest} does not match expected {expected_sha256}.")
    frame = box_baseline(load_results(BytesIO(source_bytes)), dataset_root, split_root)
    summary = describe(frame)
    summary["bootstrap"] = {cluster: cluster_bootstrap(frame, BOOTSTRAP_COLUMNS, cluster)
                            for cluster in BOOTSTRAP_CLUSTERS}
    summary["bootstrap"]["primary_cluster"] = "group_id"
    summary["source"] = {"filename": results.name, "sha256": digest,
                         "inputs_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                           for name, path in (("coco.json", dataset_root / "coco.json"),
                                                              *((f"coco_{s}.json", split_root / f"coco_{s}.json")
                                                                for s in SPLITS))}}
    summary["package_versions"] = _versions()
    summary["conventions"] = {
        "box_mask": "XYWH bbox as polygon [x,y, x+w,y, x+w,y+h, x,y+h]; pycocotools frPyObjects -> merge -> decode",
        "reference_mask": "canonical COCO polygons via dataset.reference_mask",
        "metrics": "dataset.overlap_metrics(box_mask, reference_mask)",
        "sam_metrics": "dice/iou consumed from results.csv, not recomputed",
        "fill_ratio": "reference_area_pixels / box_area_pixels",
        "gain": "SAM metric minus box metric",
        "positive_dice_gain": "dice_gain > 0 (strict)",
        "box_dice_threshold": f">= {BOX_DICE_THRESHOLD} (descriptive, not clinical)",
        "terciles": "equal-frequency on fill_ratio ranks, ties by ascending annotation_id; exploratory",
        "medians_quantiles": "linear interpolation",
        "unit": "annotation",
        "bootstrap": {"seed": SEED, "n_resamples": N_RESAMPLES, "level": LEVEL,
                      "primary_cluster": "group_id", "sensitivity_cluster": "image_id"},
    }
    serialized = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output / "box_baseline.csv", index=False, lineterminator="\n")
    (output / "box_baseline_summary.json").write_text(serialized, encoding="utf-8")
    _figure(frame, summary, output, language)
    return summary

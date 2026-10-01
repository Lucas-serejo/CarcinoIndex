"""Deterministic annotation-level summaries; no inference or clinical thresholds."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

SPLITS = ("train", "val", "test")
NUMERIC = (
    "image_id", "annotation_id", "width", "height", "reference_area_pixels",
    "predicted_area_pixels", "dice", "iou", "selected_index", "selected_score",
    "prediction_time_seconds",
)
REQUIRED = ("dataset", "split", "group_id", "file_name", *NUMERIC)
BINS = (0.0, 0.5, 0.7, 0.8, 0.9, 1.0)
BIN_LABELS = ("[0.0, 0.5)", "[0.5, 0.7)", "[0.7, 0.8)", "[0.8, 0.9)", "[0.9, 1.0]")


def load_results(path: Path) -> pd.DataFrame:
    """Validate without discarding optional bbox/polygon or other columns."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = sorted(set(REQUIRED) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError("Results must contain at least one row.")
    for name in ("dataset", "split", "group_id", "file_name"):
        if frame[name].str.strip().eq("").any():
            raise ValueError(f"{name} must not be empty.")
    if not frame.dataset.eq("ENID").all():
        raise ValueError("This analysis requires dataset ENID.")
    if not frame.split.isin(SPLITS).all():
        raise ValueError("ENID split must be train, val, or test.")
    for name in NUMERIC:
        try:
            frame[name] = pd.to_numeric(frame[name], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{name} must be numeric.") from exc
        if not np.isfinite(frame[name]).all():
            raise ValueError(f"{name} must contain finite values.")
    for name in ("image_id", "annotation_id", "width", "height", "selected_index"):
        if (frame[name] % 1 != 0).any():
            raise ValueError(f"{name} must be integer-like.")
        # Python integers retain identifiers without a forced int64 conversion.
        frame[name] = frame[name].map(int)
    if frame.annotation_id.duplicated().any():
        raise ValueError("annotation_id must be unique.")
    for name in ("dice", "iou"):
        if not frame[name].between(0, 1).all():
            raise ValueError(f"{name} must be in [0, 1].")
    for name in ("width", "height", "reference_area_pixels"):
        if (frame[name] <= 0).any():
            raise ValueError(f"{name} must be positive.")
    for name in ("predicted_area_pixels", "selected_index", "prediction_time_seconds"):
        if (frame[name] < 0).any():
            raise ValueError(f"{name} must be nonnegative.")
    with np.errstate(over="ignore", divide="ignore"):
        frame["area_ratio"] = frame.predicted_area_pixels / frame.reference_area_pixels
    if not np.isfinite(frame.area_ratio).all():
        raise ValueError("Derived area_ratio must be finite.")
    return frame.sort_values("annotation_id").reset_index(drop=True)


def _stats(values: pd.Series, *, std: bool = False) -> dict:
    result = {"mean": float(values.mean()), "median": float(values.median()),
              "min": float(values.min()), "q1": float(values.quantile(0.25)),
              "q3": float(values.quantile(0.75)), "max": float(values.max())}
    if std:
        result["std"] = float(values.std(ddof=0))
    return result


def _pearson(x: pd.Series, y: pd.Series) -> float | None:
    if len(x) < 2 or x.nunique() < 2 or y.nunique() < 2:
        return None
    # Scaling avoids overflow for large finite scores/areas without changing r.
    value = float((x / x.abs().max()).corr(y / y.abs().max()))
    return value if np.isfinite(value) else None


def _association(x: pd.Series, y: pd.Series) -> dict:
    return {"pearson": _pearson(x, y),
            "spearman": _pearson(x.rank(method="average"), y.rank(method="average"))}


def summarize(frame: pd.DataFrame) -> dict:
    return {
        "row_count": len(frame), "unique_image_count": int(frame.image_id.nunique()),
        "unique_group_id_count": int(frame.group_id.nunique()),
        "split_counts": {s: int(frame.split.eq(s).sum()) for s in SPLITS if frame.split.eq(s).any()},
        "dice": _stats(frame.dice, std=True), "iou": _stats(frame.iou, std=True),
        "selected_score": _stats(frame.selected_score),
        "reference_area_pixels": _stats(frame.reference_area_pixels),
        "correlations": {f"{name}_vs_dice": _association(frame[name], frame.dice)
                         for name in ("selected_score", "reference_area_pixels")},
        "conventions": {"standard_deviation_ddof": 0, "quartiles": "linear interpolation",
                        "spearman_ties": "average ranks", "undefined_correlation": None,
                        "unit": "annotation", "association": "descriptive/exploratory"},
    }


def by_split(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for split in (*SPLITS, "overall"):
        subset = frame if split == "overall" else frame[frame.split.eq(split)]
        if subset.empty:
            continue
        rows.append({"split": split, "count": len(subset),
                     **{f"{metric}_{key}": value for metric in ("dice", "iou")
                        for key, value in _stats(subset[metric]).items()}})
    return pd.DataFrame(rows)


def distribution(frame: pd.DataFrame) -> pd.DataFrame:
    counts, _ = np.histogram(frame.dice, bins=BINS)
    return pd.DataFrame({"label": BIN_LABELS, "count": counts,
                         "percentage": counts / len(frame) * 100})


def extreme_cases(frame: pd.DataFrame) -> pd.DataFrame:
    selections = []
    for reason, subset, column, ascending in (
        ("lowest_dice", frame, "dice", True),
        ("highest_dice", frame, "dice", False),
        ("relative_under_segmentation", frame[frame.area_ratio < 1], "area_ratio", True),
        ("relative_over_segmentation", frame[frame.area_ratio > 1], "area_ratio", False),
    ):
        selected = subset.sort_values([column, "annotation_id"], ascending=[ascending, True]).head(5).copy()
        selected.insert(0, "rank", range(1, len(selected) + 1))
        selected.insert(0, "selection_reason", reason)
        selections.append(selected)
    # One row per reason; preserve optional source columns for later inspection.
    return pd.concat(selections, ignore_index=True)


def _figures(frame: pd.DataFrame, summary: dict, output: Path) -> None:
    def figure():
        fig = Figure(figsize=(6.4, 4.2), layout="constrained")
        FigureCanvasAgg(fig)
        return fig, fig.subplots()

    def save(fig, name):
        fig.savefig(output / f"{name}.png", dpi=180, metadata={"Software": "CarcinoIndex"})
        fig.clear()

    for metric, label in (("dice", "Dice"), ("iou", "IoU")):
        fig, ax = figure()
        ax.hist(frame[metric], bins=np.linspace(0, 1, 21), color="0.4", edgecolor="white")
        ax.axvline(summary[metric]["median"], color="black", linestyle="--", label="Median")
        ax.set(xlim=(0, 1), xlabel=label, ylabel="Annotation count",
               title=f"Annotation-level {label} distribution")
        ax.legend(frameon=False)
        save(fig, f"{metric}_distribution")
    for name, label in (("selected_score", "SAM selected score"),
                        ("reference_area_pixels", "Reference-mask area (pixels; log scale)")):
        fig, ax = figure()
        ax.scatter(frame[name], frame.dice, s=18, color="0.25", alpha=0.65)
        ax.set(xlabel=label, ylabel="Dice", ylim=(0, 1), title="Annotation-level exploratory association")
        if name == "reference_area_pixels":
            ax.set_xscale("log")
        correlations = summary["correlations"][f"{name}_vs_dice"]
        text = "\n".join(f"{key.capitalize()}: {value:.3f}" if value is not None
                         else f"{key.capitalize()}: undefined" for key, value in correlations.items())
        ax.text(0.03, 0.03, text, transform=ax.transAxes, fontsize=9,
                bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
        save(fig, "selected_score_vs_dice" if name == "selected_score" else "reference_area_vs_dice")


def analyze_results(*, results: Path, output: Path) -> dict:
    """Read only the CSV and write eight artifacts to a new or empty directory."""
    results, output = Path(results), Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be empty; use a new analysis directory.")
    frame = load_results(results)
    summary = summarize(frame)
    serialized = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    (output / "descriptive_summary.json").write_text(serialized, encoding="utf-8")
    for name, table in (("descriptive_by_split", by_split(frame)),
                        ("dice_distribution", distribution(frame)),
                        ("extreme_cases", extreme_cases(frame))):
        table.to_csv(output / f"{name}.csv", index=False, lineterminator="\n")
    _figures(frame, summary, output)
    return summary

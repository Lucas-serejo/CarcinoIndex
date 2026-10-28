"""Consolidate the box-prompt robustness run: tables, cluster-bootstrap CIs and a figure; CPU only."""

from __future__ import annotations

from .box_baseline import LEVEL, N_RESAMPLES, SEED, TERCILE_LABELS, _versions, cluster_bootstrap
from .localization import localize_figure, validate_language

import hashlib
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Text

ORDER = ("ref", "ref_single", "jitter10", "expand10", "expand20")
PERTURBED = ("jitter10", "expand10", "expand20")
FIGURE_ORDER = ("ref", "jitter10", "expand10", "expand20")
CLUSTERS = ("group_id", "image_id")
NUMERIC = ("image_id", "annotation_id", "reference_area_pixels", "predicted_area_pixels", "dice", "iou",
           "selected_index", "selected_score", "prediction_time_seconds", "prompt_box_area_pixels",
           "prompt_box_dice", "prompt_box_iou")
REQUIRED = ("split", "group_id", "condition", "clipped", *NUMERIC)
TIMING_REQUIRED = ("image_id", "width", "height", "embedding_time_seconds")
TICKS = {"en": {"ref": "Reference", "jitter10": "Jitter ±10%", "expand10": "Expand 10%",
                "expand20": "Expand 20%"},
         "pt-BR": {"ref": "Referência", "jitter10": "Perturbação ±10%", "expand10": "Expansão 10%",
                   "expand20": "Expansão 20%"}}
# Supplements localization.PT_BR for this figure only; exact-match, applied after localize_figure.
PT_BR_EXTRA = {
    "Mean Dice by box-prompt condition": "Dice médio por condição da caixa delimitadora",
    "Box-prompt condition": "Condição da caixa delimitadora usada como prompt",
    "Mean Dice (95% CI, group_id cluster bootstrap)": "Dice médio (IC 95%, bootstrap por group_id)",
    "SAM 2.1 selected mask": "Máscara selecionada pelo SAM 2.1",
    "Filled prompt box": "Caixa delimitadora preenchida",
}


def _frame(source: bytes, required, name: str) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(source), dtype=str, keep_default_na=False)
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError(f"{name} must contain rows.")
    return frame


def _numeric(frame: pd.DataFrame, columns, name: str) -> None:
    for column in columns:
        try:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{name}: {column} must be numeric.") from exc
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"{name}: {column} must be finite.")


def load_long(source: bytes) -> pd.DataFrame:
    """Validate results_long.csv: all five conditions over one identical annotation set."""
    frame = _frame(source, REQUIRED, "results_long.csv")
    _numeric(frame, NUMERIC, "results_long.csv")
    for column in ("image_id", "annotation_id"):
        if (frame[column] % 1 != 0).any():
            raise ValueError(f"{column} must be integer-like.")
        frame[column] = frame[column].map(int)
    if not frame.clipped.isin(("True", "False")).all():
        raise ValueError("clipped must be True or False.")
    frame["clipped"] = frame.clipped.eq("True")
    if set(frame.condition) != set(ORDER):
        raise ValueError(f"Conditions must be exactly {', '.join(ORDER)}.")
    if frame.duplicated(["annotation_id", "condition"]).any():
        raise ValueError("annotation_id x condition must be unique.")
    for column in ("dice", "iou", "prompt_box_dice", "prompt_box_iou"):
        if not frame[column].between(0, 1).all():
            raise ValueError(f"{column} must be in [0, 1].")
    if (frame.prompt_box_area_pixels <= 0).any() or (frame.reference_area_pixels <= 0).any():
        raise ValueError("Areas must be positive.")
    reference = set(frame.annotation_id[frame.condition.eq("ref")])
    for condition in ORDER:
        if set(frame.annotation_id[frame.condition.eq(condition)]) != reference:
            raise ValueError(f"Condition {condition} does not cover the ref annotation set.")
    frame["gain"] = frame.dice - frame.prompt_box_dice
    return frame.sort_values(["annotation_id", "condition"]).reset_index(drop=True)


def paired(frame: pd.DataFrame, condition: str) -> pd.DataFrame:
    """One row per annotation of a condition, joined to ref by annotation_id."""
    ref = frame[frame.condition.eq("ref")][["annotation_id", "group_id", "image_id", "dice",
                                            "prompt_box_dice"]]
    subset = frame[frame.condition.eq(condition)]
    merged = subset.merge(ref, on="annotation_id", suffixes=("", "_ref"), validate="one_to_one")
    if len(merged) != len(ref) or len(merged) != len(subset):
        raise ValueError(f"Condition {condition} and ref annotation sets differ.")
    if not (merged.group_id.eq(merged.group_id_ref).all() and merged.image_id.eq(merged.image_id_ref).all()):
        raise ValueError(f"Condition {condition} disagrees with ref on group_id/image_id.")
    merged["delta_dice_vs_ref"] = merged.dice - merged.dice_ref
    merged["delta_box_dice_vs_ref"] = merged.prompt_box_dice - merged.prompt_box_dice_ref
    return merged.sort_values("annotation_id").reset_index(drop=True)


def _ci_columns(result: dict, cluster: str) -> dict:
    return {f"{name}_ci_{bound}_{cluster}": values[f"ci_{bound}"]
            for name, values in result["columns"].items() for bound in ("lower", "upper")}


def by_condition(frame: pd.DataFrame, n_resamples=N_RESAMPLES, seed=SEED, level=LEVEL) -> pd.DataFrame:
    rows = []
    for condition in ORDER:
        data = paired(frame, condition)
        columns = ["dice", "iou", "gain", "prompt_box_dice"] + (
            [] if condition == "ref" else ["delta_dice_vs_ref"])
        beats = int((data.dice > data.prompt_box_dice).sum())
        row = {"condition": condition, "n": len(data),
               "dice_mean": data.dice.mean(), "dice_median": data.dice.median(),
               "iou_mean": data.iou.mean(), "prompt_box_dice_mean": data.prompt_box_dice.mean(),
               "gain_mean": data.gain.mean(), "sam_beats_box_count": beats,
               "sam_beats_box_percentage": beats / len(data) * 100,
               "clipped_count": int(data.clipped.sum()),
               "delta_dice_vs_ref_mean": None if condition == "ref" else data.delta_dice_vs_ref.mean()}
        for cluster in CLUSTERS:
            row.update(_ci_columns(cluster_bootstrap(data, columns, cluster, n_resamples, seed, level), cluster))
        rows.append(row)
    return pd.DataFrame(rows)


def paired_summary(frame: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Paired change vs ref; absorbed fraction is descriptive (on means, no CI)."""
    rows = []
    for condition in ORDER[1:]:
        data = paired(frame, condition)
        box_loss = -data.delta_box_dice_vs_ref.mean()
        sam_loss = -data.delta_dice_vs_ref.mean()
        absorbed = 1 - sam_loss / box_loss if condition in PERTURBED and box_loss != 0 else None
        stats = table.set_index("condition").loc[condition]
        rows.append({
            "condition": condition, "n": len(data),
            "delta_dice_vs_ref_mean": data.delta_dice_vs_ref.mean(),
            "delta_dice_vs_ref_median": data.delta_dice_vs_ref.median(),
            **{f"delta_dice_vs_ref_ci_{b}_{c}": stats[f"delta_dice_vs_ref_ci_{b}_{c}"]
               for c in CLUSTERS for b in ("lower", "upper")},
            "better_than_ref": int((data.delta_dice_vs_ref > 0).sum()),
            "equal_to_ref": int((data.delta_dice_vs_ref == 0).sum()),
            "worse_than_ref": int((data.delta_dice_vs_ref < 0).sum()),
            "box_loss_vs_ref": box_loss if condition in PERTURBED else None,
            "sam_loss_vs_ref": sam_loss if condition in PERTURBED else None,
            "absorbed_fraction": absorbed,
        })
    return pd.DataFrame(rows)


def assign_terciles(frame: pd.DataFrame) -> pd.DataFrame:
    """Same rule as box_baseline: equal-frequency on fill_ratio ranks, ties by annotation_id."""
    ordered = frame.sort_values("annotation_id").copy()
    ordered["tercile"] = pd.qcut(ordered.fill_ratio.rank(method="first"), 3, labels=TERCILE_LABELS)
    return ordered


def normalized_gain(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Exploratory, ref only: (dice - box) / (1 - box); undefined (NaN) when box Dice is 1."""
    ref = frame[frame.condition.eq("ref")].copy()
    undefined = ref.prompt_box_dice.eq(1)
    ref["normalized_gain"] = np.where(undefined, np.nan,
                                      ref.gain / (1 - ref.prompt_box_dice.where(~undefined, 0)))
    ref["fill_ratio"] = ref.reference_area_pixels / ref.prompt_box_area_pixels
    ref = assign_terciles(ref)
    overall = {"n": len(ref), "undefined_count": int(undefined.sum()),
               "mean": float(ref.normalized_gain.mean()), "median": float(ref.normalized_gain.median())}
    rows = []
    for label in TERCILE_LABELS:
        subset = ref[ref.tercile.eq(label)]
        beats = int((subset.dice > subset.prompt_box_dice).sum())
        rows.append({"tercile": label, "n": len(subset),
                     "fill_ratio_min": subset.fill_ratio.min(), "fill_ratio_max": subset.fill_ratio.max(),
                     "fill_ratio_median": subset.fill_ratio.median(), "gain_median": subset.gain.median(),
                     "normalized_gain_median": subset.normalized_gain.median(),
                     "normalized_gain_undefined": int(subset.normalized_gain.isna().sum()),
                     "sam_beats_box_percentage": beats / len(subset) * 100})
    return overall, pd.DataFrame(rows)


def timing_summary(frame: pd.DataFrame, timing: pd.DataFrame) -> pd.DataFrame:
    def row(measure, condition, values):
        return {"measure": measure, "condition": condition, "n": len(values),
                "median": values.median(), "p5": values.quantile(0.05), "p95": values.quantile(0.95)}
    rows = [row("embedding_time_seconds", "all images", timing.embedding_time_seconds)]
    rows += [row("prediction_time_seconds", c, frame.prediction_time_seconds[frame.condition.eq(c)])
             for c in ORDER]
    rows.append(row("prediction_time_seconds", "overall", frame.prediction_time_seconds))
    return pd.DataFrame(rows)


def _figure(table: pd.DataFrame, output: Path, language: str) -> None:
    fig = Figure(figsize=(6.4, 4.2), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    stats = table.set_index("condition").loc[list(FIGURE_ORDER)]
    x = np.arange(len(FIGURE_ORDER))
    for offset, prefix, mean, label, style in (
        (-0.08, "dice", "dice_mean", "SAM 2.1 selected mask",
         dict(fmt="o", color="black", markerfacecolor="black")),
        (0.08, "prompt_box_dice", "prompt_box_dice_mean", "Filled prompt box",
         dict(fmt="s", color="0.45", markerfacecolor="white", markeredgewidth=1.5)),
    ):
        centre = stats[mean].to_numpy()
        # Clip float round-off (CI bound == mean for constant data) so error bars stay nonnegative.
        errors = np.clip([centre - stats[f"{prefix}_ci_lower_group_id"].to_numpy(),
                          stats[f"{prefix}_ci_upper_group_id"].to_numpy() - centre], 0, None)
        ax.errorbar(x + offset, centre, yerr=errors, capsize=4, markersize=7, linewidth=1.2,
                    label=label, **style)
    ax.set_xticks(x, [TICKS[language][name] for name in FIGURE_ORDER])
    ax.set(xlim=(-0.5, len(FIGURE_ORDER) - 0.5), ylim=(0.4, 1.0), xlabel="Box-prompt condition",
           ylabel="Mean Dice (95% CI, group_id cluster bootstrap)",
           title="Mean Dice by box-prompt condition")
    ax.grid(axis="y", color="0.9", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower left")
    localize_figure(fig, language)
    if language == "pt-BR":
        for artist in fig.findobj(match=Text):
            if artist.get_text() in PT_BR_EXTRA:
                artist.set_text(PT_BR_EXTRA[artist.get_text()])
    fig.savefig(output / "robustness_dice_by_condition.png", dpi=180, metadata={"Software": "CarcinoIndex"})
    fig.clear()


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    return value


def analyze_robustness(*, results: Path, output: Path, timing: Path | None = None,
                       language: str = "en", expected_sha256: str | None = None) -> dict:
    """Read results_long.csv and image_timing.csv; write six artifacts to a new or empty directory."""
    validate_language(language)
    results, output = Path(results), Path(output)
    timing = Path(timing) if timing is not None else results.parent / "image_timing.csv"
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be empty; use a new analysis directory.")
    source, timing_source = results.read_bytes(), timing.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ValueError(f"results SHA-256 {digest} does not match expected {expected_sha256}.")
    frame = load_long(source)
    timing_frame = _frame(timing_source, TIMING_REQUIRED, "image_timing.csv")
    _numeric(timing_frame, TIMING_REQUIRED, "image_timing.csv")
    if set(timing_frame.image_id) != set(frame.image_id) or timing_frame.image_id.duplicated().any():
        raise ValueError("image_timing.csv must have one row per image in results_long.csv.")

    table = by_condition(frame)
    paired_table = paired_summary(frame, table)
    gain_overall, terciles = normalized_gain(frame)
    timings = timing_summary(frame, timing_frame)
    summary = _clean({
        "source": {"results_filename": results.name, "results_sha256": digest,
                   "timing_filename": timing.name, "timing_sha256": hashlib.sha256(timing_source).hexdigest()},
        "row_count": len(frame), "annotation_count": int(frame.annotation_id.nunique()),
        "unique_image_count": int(frame.image_id.nunique()),
        "unique_group_id_count": int(frame.group_id.nunique()),
        "by_condition": table.to_dict(orient="records"),
        "paired_vs_ref": paired_table.to_dict(orient="records"),
        "normalized_gain_ref": {"label": "exploratory", **gain_overall,
                                "by_tercile": terciles.to_dict(orient="records")},
        "timing": {"rows": timings.to_dict(orient="records"),
                   "note": "Times are comparable only within the same execution."},
        "package_versions": _versions(),
        "conventions": {
            "bootstrap": {"function": "box_baseline.cluster_bootstrap", "seed": SEED,
                          "n_resamples": N_RESAMPLES, "level": LEVEL, "method": "percentile",
                          "primary_cluster": "group_id", "sensitivity_cluster": "image_id",
                          "shared_draws": "one bootstrap per condition with the same seed over the same "
                                          "annotations and clusters, so all conditions use the same "
                                          "resampling matrix (per cluster type)"},
            "gain": "dice - prompt_box_dice, per annotation",
            "delta_dice_vs_ref": "condition dice - ref dice, per annotation joined on annotation_id, "
                                 "computed before the bootstrap",
            "better_equal_worse": "delta_dice_vs_ref > 0, == 0, < 0 (exact)",
            "box_loss_vs_ref": "mean(ref prompt_box_dice) - mean(condition prompt_box_dice)",
            "sam_loss_vs_ref": "mean(ref dice) - mean(condition dice)",
            "absorbed_fraction": "1 - sam_loss / box_loss on means; descriptive, no CI; "
                                 "jitter10, expand10, expand20 only",
            "normalized_gain": "(dice - prompt_box_dice) / (1 - prompt_box_dice), ref only; "
                               "undefined (null) when prompt_box_dice == 1; exploratory",
            "fill_ratio": "reference_area_pixels / prompt_box_area_pixels (ref prompt)",
            "terciles": "box_baseline rule: equal-frequency on fill_ratio ranks, ties by ascending "
                        "annotation_id; exploratory",
            "sam_beats_box": "dice > prompt_box_dice (strict)",
            "quantiles": "linear interpolation",
            "timing": "comparable only within the same execution",
            "figure": "ref, jitter10, expand10, expand20; ref_single excluded; error bars are "
                      "group_id cluster-bootstrap 95% CIs",
        },
    })
    serialized = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    (output / "robustness_summary.json").write_text(serialized, encoding="utf-8")
    for name, data in (("robustness_by_condition", table), ("robustness_paired", paired_table),
                       ("normalized_gain_by_tercile", terciles), ("timing_summary", timings)):
        data.to_csv(output / f"{name}.csv", index=False, lineterminator="\n")
    _figure(table, output, language)
    return summary

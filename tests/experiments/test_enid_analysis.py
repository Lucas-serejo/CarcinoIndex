"""Synthetic CPU-only checks for the post-benchmark analysis contract."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.analysis.enid.analysis import (
    analyze_results, by_split, distribution, extreme_cases, load_results, summarize,
)


@pytest.fixture
def rows():
    return pd.DataFrame({
        "dataset": ["ENID"] * 6, "split": ["train", "train", "val", "val", "test", "test"],
        "group_id": ["001", "001", "002", "002", "003", "003"],
        "image_id": [1, 1, 2, 3, 4, 4], "annotation_id": [1, 2, 3, 4, 5, 6],
        "file_name": [f"synthetic-{i}.png" for i in range(6)],
        "width": [100] * 6, "height": [100] * 6,
        "reference_area_pixels": [10, 20, 30, 40, 50, 60],
        "predicted_area_pixels": [0, 10, 30, 80, 150, 180],
        "dice": [0, .5, .7, .8, .9, 1], "iou": [0, .2, .4, .6, .8, 1],
        "selected_index": [0] * 6, "selected_score": [0, 1, 1, 2, 3, 4],
        "prediction_time_seconds": [.1] * 6,
        "bbox_x": [2] * 6, "polygon_count": [1] * 6,
    })


def write_results(tmp_path, rows):
    path = tmp_path / "results.csv"
    rows.to_csv(path, index=False)
    return path


@pytest.mark.parametrize("column", [
    "dataset", "split", "group_id", "image_id", "annotation_id", "file_name",
    "width", "height", "reference_area_pixels", "predicted_area_pixels", "dice", "iou",
    "selected_index", "selected_score", "prediction_time_seconds",
])
def test_required_columns(tmp_path, rows, column):
    with pytest.raises(ValueError, match="Missing required columns"):
        load_results(write_results(tmp_path, rows.drop(columns=column)))


@pytest.mark.parametrize("column,value,match", [
    ("dice", "oops", "numeric"), ("iou", np.nan, "finite"),
    ("selected_score", np.inf, "finite"), ("prediction_time_seconds", -np.inf, "finite"),
    ("reference_area_pixels", np.inf, "finite"), ("predicted_area_pixels", "bad", "numeric"),
    ("width", "bad", "numeric"), ("height", 0, "positive"),
    ("selected_index", .5, "integer-like"), ("selected_index", -1, "nonnegative"),
    ("prediction_time_seconds", -.1, "nonnegative"),
    ("image_id", 1.5, "integer-like"), ("annotation_id", 1.5, "integer-like"),
    ("annotation_id", 2, "unique"), ("dice", -0.01, r"\[0, 1\]"),
    ("dice", 1.01, r"\[0, 1\]"), ("iou", -0.1, r"\[0, 1\]"),
    ("iou", 1.1, r"\[0, 1\]"), ("reference_area_pixels", 0, "positive"),
    ("reference_area_pixels", -1, "positive"), ("predicted_area_pixels", -1, "nonnegative"),
    ("split", "validation", "split"), ("dataset", "other", "ENID"),
    ("group_id", "", "empty"),
])
def test_invalid_values(tmp_path, rows, column, value, match):
    rows[column] = rows[column].astype(object)
    rows.loc[0, column] = value
    with pytest.raises(ValueError, match=match):
        load_results(write_results(tmp_path, rows))


def test_empty_input(tmp_path, rows):
    with pytest.raises(ValueError, match="at least one"):
        load_results(write_results(tmp_path, rows.iloc[:0]))


def test_statistics_and_correlations(tmp_path, rows):
    frame = load_results(write_results(tmp_path, rows))
    result = summarize(frame)
    assert result["row_count"] == 6
    assert result["unique_image_count"] == 4
    assert result["unique_group_id_count"] == 3
    assert frame.group_id.tolist() == ["001", "001", "002", "002", "003", "003"]
    assert result["split_counts"] == {"train": 2, "val": 2, "test": 2}
    assert result["dice"] == pytest.approx({
        "mean": .65, "median": .75, "std": np.sqrt(.655 / 6),
        "min": 0, "q1": .55, "q3": .875, "max": 1,
    })
    assert result["iou"]["q1"] == pytest.approx(.25)
    assert result["iou"]["q3"] == pytest.approx(.75)
    score = result["correlations"]["selected_score_vs_dice"]
    assert score["pearson"] == pytest.approx(np.corrcoef(rows.selected_score, rows.dice)[0, 1])
    assert score["spearman"] == pytest.approx(np.corrcoef([1, 2.5, 2.5, 4, 5, 6], [1, 2, 3, 4, 5, 6])[0, 1])
    area = result["correlations"]["reference_area_pixels_vs_dice"]
    assert area["pearson"] == pytest.approx(np.corrcoef(rows.reference_area_pixels, rows.dice)[0, 1])
    assert area["spearman"] == pytest.approx(1)


def test_splits_bins_and_candidates(tmp_path, rows):
    frame = load_results(write_results(tmp_path, rows))
    splits = by_split(frame)
    assert splits.split.tolist() == ["train", "val", "test", "overall"]
    assert splits["count"].tolist() == [2, 2, 2, 6]
    assert splits.dice_mean.tolist() == pytest.approx([.25, .75, .95, .65])
    assert by_split(frame[frame.split == "val"]).split.tolist() == ["val", "overall"]
    bins = distribution(frame)
    assert bins["count"].tolist() == [1, 1, 1, 1, 2]
    assert bins.percentage.tolist() == pytest.approx([100 / 6] * 4 + [100 / 3])
    cases = extreme_cases(frame)
    assert cases.groupby("selection_reason").annotation_id.apply(list).to_dict() == {
        "lowest_dice": [1, 2, 3, 4, 5], "highest_dice": [6, 5, 4, 3, 2],
        "smallest_predicted_reference_area_ratio": [1, 2],
        "largest_predicted_reference_area_ratio": [5, 6, 4],
    }
    assert cases[cases.selection_reason == "largest_predicted_reference_area_ratio"].area_ratio.tolist() == [3, 3, 2]
    assert "bbox_x" in cases and "polygon_count" in cases
    tied = frame.copy()
    tied["dice"] = .5
    assert extreme_cases(tied).query("selection_reason == 'highest_dice'").annotation_id.tolist() == [1, 2, 3, 4, 5]


def test_artifacts_and_reproducibility(tmp_path, rows):
    source = write_results(tmp_path, rows)
    original = source.read_bytes()
    first, second = tmp_path / "first", tmp_path / "second"
    summary = analyze_results(results=source, output=first)
    second.mkdir()
    assert analyze_results(results=source, output=second) == summary
    names = {"descriptive_summary.json", "descriptive_by_split.csv", "dice_distribution.csv",
             "extreme_cases.csv", "dice_distribution.png", "iou_distribution.png",
             "selected_score_vs_dice.png", "reference_area_vs_dice.png"}
    assert {p.name for p in first.iterdir()} == names
    for name in names:
        assert (first / name).stat().st_size > 0
        if not name.endswith(".png"):
            assert (first / name).read_bytes() == (second / name).read_bytes()
    assert json.loads((first / "descriptive_summary.json").read_text(),
                      parse_constant=lambda v: pytest.fail(f"Invalid JSON constant {v}")) == summary
    assert source.read_bytes() == original
    with pytest.raises(ValueError, match="must be empty"):
        analyze_results(results=source, output=first)
    assert (first / "descriptive_summary.json").read_bytes() == (second / "descriptive_summary.json").read_bytes()


@pytest.mark.parametrize("change", ["line_endings", "row_order"])
def test_source_hash_tracks_exact_input_bytes(tmp_path, rows, change):
    source = write_results(tmp_path, rows)
    original = source.read_bytes()
    first = analyze_results(results=source, output=tmp_path / "first")
    assert first["source"] == {"filename": "results.csv", "sha256": hashlib.sha256(original).hexdigest()}
    if change == "line_endings":
        changed = original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if changed == original:
            changed = original.replace(b"\r\n", b"\n")
        source.write_bytes(changed)
    else:
        write_results(tmp_path, rows.sample(frac=1, random_state=3))
    changed = source.read_bytes()
    assert changed != original
    second = analyze_results(results=source, output=tmp_path / "second")
    assert second["source"] == {"filename": "results.csv", "sha256": hashlib.sha256(changed).hexdigest()}
    assert second["source"]["sha256"] != first["source"]["sha256"]
    for name, result in (("first", first), ("second", second)):
        assert json.loads((tmp_path / name / "descriptive_summary.json").read_text()) == result
    assert {k: v for k, v in first.items() if k != "source"} == {
        k: v for k, v in second.items() if k != "source"
    }
    for name in ("descriptive_by_split.csv", "dice_distribution.csv", "extreme_cases.csv"):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()
    assert source.read_bytes() == changed


@pytest.mark.parametrize("single", [True, False])
def test_undefined_correlations_and_headless_figures(tmp_path, rows, single):
    rows = rows.iloc[:1].copy() if single else rows.copy()
    rows["selected_score"] = 0
    rows["reference_area_pixels"] = 10
    output = tmp_path / "analysis"
    result = analyze_results(results=write_results(tmp_path, rows), output=output)
    assert all(value is None for pair in result["correlations"].values() for value in pair.values())
    if single:
        assert result["dice"]["std"] == 0
    serialized = (output / "descriptive_summary.json").read_text()
    assert "NaN" not in serialized and "Infinity" not in serialized
    assert len(list(output.glob("*.png"))) == 4


def test_invalid_input_does_not_create_output(tmp_path, rows):
    output = tmp_path / "analysis"
    with pytest.raises(ValueError):
        analyze_results(results=write_results(tmp_path, rows.drop(columns="dice")), output=output)
    assert not output.exists()


def test_cli(tmp_path, rows):
    source = write_results(tmp_path, rows)
    script = Path(__file__).resolve().parents[2] / "scripts" / "analyze_enid_results.py"
    command = [sys.executable, str(script), "--results", str(source), "--output", str(tmp_path / "cli output")]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "6 annotations" in result.stdout
    rejected = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert rejected.returncode == 1
    assert "must be empty" in rejected.stderr

"""Synthetic CPU-only checks for the box-robustness analysis."""

import json

import numpy as np
import pandas as pd
import pytest

from experiments.analysis.enid.box_baseline import _terciles
from experiments.analysis.enid.robustness_analysis import (
    ORDER, analyze_robustness, assign_terciles, by_condition, load_long, normalized_gain, paired,
    paired_summary,
)
from scripts.analyze_enid_box_robustness import main

N = 9
# Per condition: (dice, prompt_box_dice) for every annotation, unless overridden per annotation.
VALUES = {"ref": (0.90, 0.80), "ref_single": (0.92, 0.80), "jitter10": (0.89, 0.78),
          "expand10": (0.85, 0.60), "expand20": (0.80, 0.50)}


def make_long(overrides=None):
    rows = []
    for aid in range(N):
        for condition in ORDER:
            dice, box = (overrides or {}).get((aid, condition), VALUES[condition])
            rows.append(dict(split="train", group_id=f"c_{aid // 3}", image_id=aid // 2,
                             annotation_id=aid, condition=condition, prompt_x_min=1.0, prompt_y_min=1.0,
                             prompt_x_max=5.0, prompt_y_max=5.0, clipped=condition == "expand20" and aid == 0,
                             reference_area_pixels=10 + aid, predicted_area_pixels=12, dice=dice,
                             iou=dice / (2 - dice), selected_index=0, selected_score=0.9,
                             prediction_time_seconds=0.01 * (1 + aid), prompt_box_area_pixels=16,
                             prompt_box_dice=box, prompt_box_iou=box / (2 - box)))
    return pd.DataFrame(rows)


@pytest.fixture
def inputs(tmp_path):
    results, timing = tmp_path / "results_long.csv", tmp_path / "image_timing.csv"
    make_long().to_csv(results, index=False)
    pd.DataFrame({"image_id": range(5), "width": 8, "height": 8,
                  "embedding_time_seconds": [0.1, 0.2, 0.3, 0.4, 0.5]}).to_csv(timing, index=False)
    return dict(results=results, output=tmp_path / "out")


def load(frame):
    return load_long(frame.to_csv(index=False).encode())


def test_paired_difference_is_computed_per_annotation():
    overrides = {(aid, "ref_single"): (0.5 + aid / 20, 0.8) for aid in range(N)}
    overrides.update({(aid, "ref"): (0.9 - aid / 40, 0.8) for aid in range(N)})
    shuffled = make_long(overrides).sample(frac=1, random_state=3)  # row order must not matter
    data = paired(load(shuffled), "ref_single")
    expected = [(0.5 + aid / 20) - (0.9 - aid / 40) for aid in range(N)]
    assert data.annotation_id.tolist() == list(range(N))
    assert data.delta_dice_vs_ref.to_numpy() == pytest.approx(expected)
    with pytest.raises(ValueError, match="does not cover"):
        load(make_long().query("not (annotation_id == 4 and condition == 'expand10')"))


def test_absorbed_fraction_and_better_equal_worse_known_case():
    frame = load(make_long({(0, "ref_single"): (0.90, 0.80), (1, "ref_single"): (0.70, 0.80)}))
    table = paired_summary(frame, by_condition(frame, n_resamples=200)).set_index("condition")
    # expand10: box loses 0.80 - 0.60 = 0.20, SAM loses 0.90 - 0.85 = 0.05 -> absorbs 75%.
    assert table.loc["expand10", "box_loss_vs_ref"] == pytest.approx(0.20)
    assert table.loc["expand10", "sam_loss_vs_ref"] == pytest.approx(0.05)
    assert table.loc["expand10", "absorbed_fraction"] == pytest.approx(0.75)
    assert table.loc["expand20", "absorbed_fraction"] == pytest.approx(1 - 0.10 / 0.30)
    assert pd.isna(table.loc["ref_single", "absorbed_fraction"])
    assert table.loc["ref_single", ["better_than_ref", "equal_to_ref", "worse_than_ref"]].tolist() == [7, 1, 1]


def test_normalized_gain_marks_unit_box_dice_as_undefined():
    frame = load(make_long({(0, "ref"): (0.95, 1.0), (1, "ref"): (1.0, 1.0)}))
    overall, terciles = normalized_gain(frame)
    assert overall["undefined_count"] == 2 and overall["n"] == N
    assert overall["mean"] == pytest.approx(0.5) and overall["median"] == pytest.approx(0.5)
    assert terciles.normalized_gain_undefined.sum() == 2 and terciles.n.tolist() == [3, 3, 3]


def test_terciles_match_box_baseline_rule():
    rng = np.random.default_rng(0)
    fill = np.round(rng.uniform(0.2, 0.9, 61), 2)  # rounding forces ties
    frame = pd.DataFrame({"annotation_id": rng.permutation(61), "fill_ratio": fill,
                          "dice": 0.8, "box_dice": 0.7, "dice_gain": 0.1})
    expected = _terciles(frame)
    ours = assign_terciles(frame)
    for row in expected:
        subset = ours[ours.tercile.eq(row["tercile"])]
        assert len(subset) == row["count"]
        assert subset.fill_ratio.min() == row["fill_ratio_min"]
        assert subset.fill_ratio.max() == row["fill_ratio_max"]


def test_nonempty_output_is_rejected(inputs):
    inputs["output"].mkdir()
    (inputs["output"] / "keep.txt").write_text("existing")
    with pytest.raises(ValueError, match="must be empty"):
        analyze_robustness(**inputs)
    assert [p.name for p in inputs["output"].iterdir()] == ["keep.txt"]


def test_hash_mismatch_aborts_before_writing(inputs, capsys):
    args = [f"--results={inputs['results']}", f"--output={inputs['output']}"]
    assert main([*args, "--expected-sha256=" + "0" * 64]) == 1
    assert "does not match" in capsys.readouterr().err
    assert not inputs["output"].exists()


def test_outputs_and_language_invariance(inputs, tmp_path):
    en = analyze_robustness(**{**inputs, "output": tmp_path / "en"})
    pt = analyze_robustness(**{**inputs, "output": tmp_path / "pt"}, language="pt-BR")
    assert en == pt
    names = {"robustness_by_condition.csv", "robustness_paired.csv", "normalized_gain_by_tercile.csv",
             "timing_summary.csv", "robustness_summary.json"}
    assert {p.name for p in (tmp_path / "en").iterdir()} == names | {"robustness_dice_by_condition.png"}
    for name in names:
        assert (tmp_path / "en" / name).read_bytes() == (tmp_path / "pt" / name).read_bytes()
    summary = json.loads((tmp_path / "en" / "robustness_summary.json").read_text())
    assert summary["conventions"]["bootstrap"]["seed"] == 20261027
    assert "same resampling matrix" in summary["conventions"]["bootstrap"]["shared_draws"]
    ref = next(row for row in summary["by_condition"] if row["condition"] == "ref")
    assert ref["delta_dice_vs_ref_mean"] is None and ref["gain_mean"] == pytest.approx(0.1)

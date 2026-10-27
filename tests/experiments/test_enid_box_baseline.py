"""Synthetic CPU-only checks for the filled-bbox baseline and cluster bootstrap."""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from experiments.analysis.enid.box_baseline import (
    analyze_box_baseline, box_mask, cluster_bootstrap,
)
from experiments.benchmarks.enid.dataset import load_samples, reference_mask
from scripts.analyze_enid_box_baseline import main

RECT = [1, 1, 4, 1, 4, 4, 1, 4]


@pytest.fixture
def enid(tmp_path):
    root, splits = tmp_path / "dataset", tmp_path / "splits"
    root.mkdir()
    splits.mkdir()
    images = [dict(id=i, file_name=f"c_{i}_v_frame.jpg", width=8 + i, height=6 + i)
              for i in range(3)]
    specs = ((0, 0, [1, 1, 3, 3], RECT), (1, 0, [1, 1, 4, 4], [1, 1, 5, 1, 1, 5]),
             (2, 1, [1, 1, 3, 3], RECT), (3, 2, [0, 0, 5, 5], RECT))
    annotations = [dict(id=aid, image_id=iid, category_id=1, iscrowd=0, bbox=bbox,
                        segmentation=[polygon]) for aid, iid, bbox, polygon in specs]
    (root / "coco.json").write_text(json.dumps(dict(images=images, annotations=annotations)))
    for iid, split in enumerate(("train", "val", "test")):
        (splits / f"coco_{split}.json").write_text(json.dumps(dict(
            images=[images[iid]], annotations=[a for a in annotations if a["image_id"] == iid])))
    rows = []
    for sample, dice in zip(load_samples(root, splits), (0.9, 0.8, 0.7, 0.6)):
        x, y, w, h = sample.bbox_xywh
        rows.append(dict(dataset="ENID", split=sample.split, group_id=sample.group_id,
                         image_id=sample.image_id, annotation_id=sample.annotation_id,
                         file_name=sample.file_name, width=sample.width, height=sample.height,
                         bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h, polygon_count=1,
                         reference_area_pixels=int(reference_mask(sample).sum()),
                         predicted_area_pixels=9, dice=dice, iou=dice / (2 - dice),
                         selected_index=0, selected_score=0.5, prediction_time_seconds=0.1))
    results = tmp_path / "results.csv"
    pd.DataFrame(rows).to_csv(results, index=False)
    return dict(dataset_root=root, split_root=splits, results=results, output=tmp_path / "out")


def clustered(sizes=(3, 1, 2, 5), seed=0):
    rng = np.random.default_rng(seed)
    cluster = np.repeat([f"c_{i}" for i in range(len(sizes))], sizes)
    return pd.DataFrame({"group_id": cluster, "x": rng.random(len(cluster)),
                         "y": rng.random(len(cluster))})


def test_rectangular_reference_equal_to_box_gives_unit_overlap(enid):
    summary = analyze_box_baseline(**enid)
    table = pd.read_csv(enid["output"] / "box_baseline.csv").set_index("annotation_id")
    for aid in (0, 2):
        row = table.loc[aid]
        assert row.box_dice == 1 and row.box_iou == 1 and row.fill_ratio == 1
        assert row.reference_pixels_outside_box == 0
        assert row.dice_gain == pytest.approx(row.dice - 1)
    assert table.loc[1].box_dice < 1 and table.loc[3].fill_ratio < 1
    assert summary["reference_pixels_outside_box"]["total"] == 0
    assert summary["source"]["sha256"] == hashlib.sha256(enid["results"].read_bytes()).hexdigest()
    assert {p.name for p in enid["output"].iterdir()} == {
        "box_baseline.csv", "box_baseline_summary.json", "dice_gain_vs_fill_ratio.png"}


def test_box_mask_matches_reference_rasterization(enid):
    for sample in load_samples(enid["dataset_root"], enid["split_root"]):
        if sample.segmentation == [RECT] and sample.bbox_xywh == (1, 1, 3, 3):
            assert np.array_equal(box_mask(sample), reference_mask(sample))


def test_bootstrap_is_deterministic_for_a_fixed_seed():
    frame = clustered()
    first = cluster_bootstrap(frame, ["x", "y"], "group_id", n_resamples=500, seed=7)
    assert first == cluster_bootstrap(frame, ["x", "y"], "group_id", n_resamples=500, seed=7)
    assert first != cluster_bootstrap(frame, ["x", "y"], "group_id", n_resamples=500, seed=8)
    assert first["seed"] == 7 and first["n_resamples"] == 500 and first["n_clusters"] == 4


def test_bootstrap_interval_contains_observed_mean():
    frame = clustered(sizes=(4, 2, 3, 5, 1, 6, 2, 3))
    result = cluster_bootstrap(frame, ["x", "y"], "group_id", n_resamples=2000)
    for name in ("x", "y"):
        stats = result["columns"][name]
        assert stats["mean"] == pytest.approx(frame[name].mean())
        assert stats["ci_lower"] <= stats["mean"] <= stats["ci_upper"]


def test_bootstrap_resamples_whole_clusters():
    # Cluster A: three rows of 0; cluster B: one row of 1. Whole-cluster draws
    # allow only AA=0, AB=1/4, BB=1; row-level draws would also yield 1/2, 3/4.
    frame = pd.DataFrame({"group_id": ["A", "A", "A", "B"], "x": [0.0, 0.0, 0.0, 1.0]})
    result = cluster_bootstrap(frame, ["x"], "group_id", n_resamples=2000, keep_replicates=True)
    assert set(np.round(result["replicates"]["x"], 12)) == {0.0, 0.25, 1.0}


def test_nonempty_output_is_rejected_without_writing(enid):
    enid["output"].mkdir()
    (enid["output"] / "keep.txt").write_text("existing")
    with pytest.raises(ValueError, match="must be empty"):
        analyze_box_baseline(**enid)
    assert [p.name for p in enid["output"].iterdir()] == ["keep.txt"]


def test_unknown_annotation_id_is_rejected(enid):
    frame = pd.read_csv(enid["results"])
    frame.loc[0, "annotation_id"] = 99
    frame.to_csv(enid["results"], index=False)
    with pytest.raises(ValueError, match="not found in canonical COCO"):
        analyze_box_baseline(**enid)
    assert not enid["output"].exists()


def test_bbox_disagreement_and_hash_mismatch_are_rejected(enid, capsys):
    with pytest.raises(ValueError, match="does not match expected"):
        analyze_box_baseline(**enid, expected_sha256="0" * 64)
    frame = pd.read_csv(enid["results"])
    frame.loc[1, "bbox_width"] += 1
    frame.to_csv(enid["results"], index=False)
    assert main([f"--{k.replace('_', '-')}={v}" for k, v in enid.items()]) == 1
    assert "disagrees with COCO bbox" in capsys.readouterr().err
    assert not enid["output"].exists()


def test_language_does_not_change_numeric_artifacts(enid, tmp_path):
    en = analyze_box_baseline(**{**enid, "output": tmp_path / "en"})
    pt = analyze_box_baseline(**{**enid, "output": tmp_path / "pt"}, language="pt-BR")
    assert en == pt
    for name in ("box_baseline.csv", "box_baseline_summary.json"):
        assert (tmp_path / "en" / name).read_bytes() == (tmp_path / "pt" / name).read_bytes()

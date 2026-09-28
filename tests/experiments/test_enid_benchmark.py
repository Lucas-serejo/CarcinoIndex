import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.ai.segmentation.sam_segmenter import SegmentationResult
from experiments.benchmarks.enid.dataset import (
    group_id, load_samples, overlap_metrics, reference_mask, xywh_to_xyxy,
)
from experiments.benchmarks.enid.runner import run_benchmark
from scripts.run_enid_benchmark import main


@pytest.fixture
def enid(tmp_path):
    root, splits = tmp_path / "dataset", tmp_path / "splits"
    (root / "frames").mkdir(parents=True)
    splits.mkdir()
    images = [dict(id=i, file_name=f"c_{i}_v_frame.jpg", width=8+i, height=6+i)
              for i in range(3)]
    annotations = [dict(id=aid, image_id=iid, category_id=1, iscrowd=0,
                        bbox=[1, 1, 3, 3], segmentation=[[1, 1, 4, 1, 4, 4, 1, 4]],
                        area=99999) for aid, iid in ((0, 0), (1, 0), (2, 1), (3, 2))]
    data = dict(images=images, annotations=annotations)
    (root / "coco.json").write_text(json.dumps(data))
    for image in images:
        Image.new("RGB", (image["width"], image["height"])).save(root / "frames" / image["file_name"])
    for iid, split in enumerate(("train", "val", "test")):
        (splits / f"coco_{split}.json").write_text(json.dumps(dict(
            images=[images[iid]], annotations=[a for a in annotations if a["image_id"] == iid])))
    checkpoint = tmp_path / "fake.pt"
    checkpoint.write_bytes(b"synthetic checkpoint")
    return root, splits, checkpoint, tmp_path / "output"


def test_samples_splits_and_deterministic_limit(enid):
    root, splits, _, _ = enid
    samples = load_samples(root, splits)
    assert [s.annotation_id for s in samples] == [0, 1, 2, 3]
    assert samples[0].image_id == samples[1].image_id
    assert [s.split for s in samples] == ["train", "train", "val", "test"]
    assert samples[0].group_id == "c_0"
    assert load_samples(root, splits, "val", 1) == [samples[2]]
    assert load_samples(root, splits, limit=3) == samples[:3]
    assert reference_mask(samples[2]).shape == (7, 9)
    assert reference_mask(samples[3]).shape == (8, 10)


def test_group_and_box_conversion():
    assert group_id("c_100_v_(video_3062.mp4)_f_1751.jpg") == "c_100"
    with pytest.raises(ValueError, match="c_<number>"):
        group_id("invalid.jpg")
    assert xywh_to_xyxy((1.5, 2, 3, 4)) == (1.5, 2, 4.5, 6)


def test_polygon_rasterization_and_union(enid):
    sample = load_samples(*enid[:2])[0]
    expected = np.zeros((6, 8), dtype=bool)
    expected[1:4, 1:4] = True
    assert np.array_equal(reference_mask(sample), expected)
    multipart = replace(sample, segmentation=sample.segmentation + [[3, 2, 6, 2, 6, 5, 3, 5]])
    expected[2:5, 3:6] = True
    assert np.array_equal(reference_mask(multipart), expected)
    assert int(reference_mask(multipart).sum()) == 16


def test_known_metrics_and_empty_convention():
    reference = np.array([[1, 1], [0, 0]], dtype=bool)
    prediction = np.array([[0, 1], [1, 0]], dtype=bool)
    metrics = overlap_metrics(prediction, reference)
    assert metrics == dict(reference_area_pixels=2, predicted_area_pixels=2, dice=0.5, iou=1/3)
    empty = np.zeros_like(reference)
    assert overlap_metrics(empty, reference)["dice"] == 0
    assert overlap_metrics(empty, empty)["dice"] == 1
    assert overlap_metrics(empty, empty)["iou"] == 1
    with pytest.raises(ValueError, match="boolean"):
        overlap_metrics(prediction.astype(int), reference)
    with pytest.raises(ValueError, match="identical"):
        overlap_metrics(prediction[:1], reference)


@pytest.mark.parametrize("field,value", [
    ("bbox", [1, 1, 0, 3]), ("bbox", [1, 1, 30, 3]), ("bbox", [1, 2]),
    ("bbox", [1, 1, float("nan"), 3]), ("bbox", [True, 1, 3, 3]),
    ("image_id", 99), ("segmentation", []), ("segmentation", {"counts": "abc"}),
    ("segmentation", [[1, 2, 3]]), ("segmentation", [[0, 0, 99, 0, 2, 2]]),
    ("iscrowd", 1),
])
def test_invalid_annotation(enid, field, value):
    root, splits, _, _ = enid
    path = root / "coco.json"
    data = json.loads(path.read_text())
    data["annotations"][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="annotation"):
        load_samples(root, splits)


@pytest.mark.parametrize("split,limit", [("invalid", None), ("all", 0), ("all", -1)])
def test_invalid_selection(enid, split, limit):
    with pytest.raises(ValueError):
        load_samples(*enid[:2], split, limit)


def test_split_overlap_and_missing_membership(enid):
    root, splits, _, _ = enid
    path = splits / "coco_val.json"
    path.write_text((splits / "coco_train.json").read_text())
    with pytest.raises(ValueError, match="overlapping"):
        load_samples(root, splits)
    path.write_text(json.dumps(dict(images=[], annotations=[])))
    with pytest.raises(ValueError, match="cover"):
        load_samples(root, splits)


class FakeSegmenter:
    instances = []
    fail_at = None

    def __init__(self, **kwargs):
        self.calls = []
        self.predictions = 0
        self.instances.append(self)

    def load(self):
        self.calls.append("load")

    def set_image(self, image):
        assert image.dtype == np.uint8 and image.shape[2] == 3
        self.shape = image.shape
        self.calls.append("set")

    def segment_with_box(self, box, multimask_output):
        assert multimask_output is True
        assert box == (1, 1, 4, 4)
        self.predictions += 1
        if self.predictions == self.fail_at:
            raise RuntimeError("Synthetic inference failure")
        # Candidate 0 is a perfect match. Candidate 1 has the highest SAM score
        # but is empty: the benchmark MUST report zero, never pick candidate 0.
        masks = np.zeros((2, *self.shape[:2]), dtype=bool)
        masks[0, 1:4, 1:4] = True
        return SegmentationResult(
            masks=masks, scores=np.array([0.2, 0.9]), logits=None,
            selected_index=1, selected_mask=masks[1], selected_score=0.9,
            prompt_type="box", prompt_data={"box_xyxy": box}, image_shape=self.shape,
            model_name="sam2.1_hiera_small", model_config="synthetic", checkpoint_name="fake.pt",
            device="cpu", dtype="float32", load_time_seconds=0, embedding_time_seconds=0,
            prediction_time_seconds=0.01, peak_vram_bytes=None,
        )

    def clear_image(self):
        self.calls.append("clear")

    def close(self):
        self.calls.append("close")


def run_fake(enid, **kwargs):
    root, splits, checkpoint, output = enid
    return run_benchmark(dataset_root=root, split_root=splits, checkpoint=checkpoint,
                         output=output, device="cpu", segmenter_factory=FakeSegmenter, **kwargs)


def test_runner_selected_mask_embedding_and_outputs(enid):
    summary = run_fake(enid, limit=3)
    assert summary["status"] == "complete"
    assert summary["success_count"] == 3 and summary["failure_count"] == 0
    assert summary["images_processed"] == 2
    assert summary["overall"]["dice"] == {"mean": 0, "median": 0}
    assert summary["by_split"]["train"]["count"] == 2
    assert len(summary["checkpoint_sha256"]) == 64
    assert len(summary["coco_sha256"]) == 64
    assert len(summary["split_sha256"]) == 3
    assert FakeSegmenter.instances[-1].calls == ["load", "set", "clear", "set", "clear", "close"]
    output = enid[3]
    with (output / "results.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [int(row["annotation_id"]) for row in rows] == [0, 1, 2]
    assert all(row["reference_area_pixels"] == "9" for row in rows)
    assert all(row["predicted_area_pixels"] == "0" and row["selected_index"] == "1" for row in rows)
    assert not (output / "results.incomplete.csv").exists()
    assert str(enid[0].parent) not in (output / "summary.json").read_text()
    with pytest.raises(ValueError, match="empty"):
        run_fake(enid)


def test_runner_failure_keeps_explicit_partial_results(enid, monkeypatch):
    monkeypatch.setattr(FakeSegmenter, "fail_at", 2)
    with pytest.raises(RuntimeError, match="annotation=1.*Synthetic inference failure"):
        run_fake(enid)
    output = enid[3]
    summary = json.loads((output / "summary.json").read_text())
    assert summary["status"] == "incomplete"
    assert summary["success_count"] == 1 and summary["failure_count"] == 1
    assert summary["failure"]["annotation_id"] == 1
    assert (output / "results.incomplete.csv").exists()
    assert not (output / "results.csv").exists()
    assert FakeSegmenter.instances[-1].calls[-2:] == ["clear", "close"]


def test_missing_checkpoint_cli_nonzero(enid, capsys):
    root, splits, checkpoint, output = enid
    checkpoint.unlink()
    assert main(["--dataset-root", str(root), "--split-root", str(splits),
                 "--checkpoint", str(checkpoint), "--output", str(output)]) == 1
    assert "Checkpoint not found" in capsys.readouterr().err
    assert json.loads((output / "summary.json").read_text())["status"] == "incomplete"


def test_invalid_json_and_missing_dataset(enid):
    root, splits, _, _ = enid
    (root / "coco.json").write_text("{")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_samples(root, splits)
    (root / "coco.json").unlink()
    with pytest.raises(ValueError, match="Cannot read coco.json"):
        load_samples(root, splits)


def test_output_cannot_write_into_dataset(enid):
    root, splits, checkpoint, _ = enid
    with pytest.raises(ValueError, match="outside"):
        run_benchmark(dataset_root=root, split_root=splits, checkpoint=checkpoint,
                      output=root / "output", segmenter_factory=FakeSegmenter)
    assert not (root / "output").exists()

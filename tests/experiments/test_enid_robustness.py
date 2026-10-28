"""Synthetic CPU-only checks for the ENID box-prompt robustness runner."""

import csv
import json

import numpy as np
import pytest
from PIL import Image
from pycocotools import mask as coco_mask

from backend.ai.segmentation.sam_segmenter import SegmentationResult
from experiments.analysis.enid.box_baseline import box_mask
from experiments.benchmarks.enid.dataset import load_samples
from experiments.benchmarks.enid.robustness import (
    CONDITIONS, SEED, Condition, perturb_box, prompt_box_mask, run_robustness,
)
from scripts.run_enid_box_robustness import main

BY_NAME = {condition.name: condition for condition in CONDITIONS}


@pytest.fixture
def enid(tmp_path):
    root, splits = tmp_path / "dataset", tmp_path / "splits"
    (root / "frames").mkdir(parents=True)
    splits.mkdir()
    images = [dict(id=i, file_name=f"c_{i}_v_frame.jpg", width=8 + i, height=6 + i)
              for i in range(3)]
    specs = ((0, 0, [1, 1, 3, 3]), (1, 0, [0, 0, 3, 3]), (2, 1, [1, 1, 3, 3]), (3, 2, [1, 1, 3, 3]))
    annotations = [dict(id=aid, image_id=iid, category_id=1, iscrowd=0, bbox=[x, y, w, h],
                        segmentation=[[x, y, x + w, y, x + w, y + h, x, y + h]])
                   for aid, iid, (x, y, w, h) in specs]
    (root / "coco.json").write_text(json.dumps(dict(images=images, annotations=annotations)))
    for image in images:
        Image.new("RGB", (image["width"], image["height"])).save(root / "frames" / image["file_name"])
    for iid, split in enumerate(("train", "val", "test")):
        (splits / f"coco_{split}.json").write_text(json.dumps(dict(
            images=[images[iid]], annotations=[a for a in annotations if a["image_id"] == iid])))
    checkpoint = tmp_path / "fake.pt"
    checkpoint.write_bytes(b"synthetic checkpoint")
    return dict(dataset_root=root, split_root=splits, checkpoint=checkpoint, output=tmp_path / "output")


class FakeSegmenter:
    instances = []
    fail_at = None

    def __init__(self, **kwargs):
        self.calls, self.prompts = [], []
        self.embedding_time_seconds = None
        self.instances.append(self)

    def load(self):
        self.calls.append("load")

    def set_image(self, image):
        assert image.dtype == np.uint8 and image.shape[2] == 3
        self.shape = image.shape
        self.embedding_time_seconds = 0.05
        self.calls.append("set")

    def segment_with_box(self, box, multimask_output):
        self.prompts.append((box, multimask_output))
        if len(self.prompts) == self.fail_at:
            raise RuntimeError("Synthetic inference failure")
        count = 3 if multimask_output else 1
        masks = np.zeros((count, *self.shape[:2]), dtype=bool)
        masks[0, 1:4, 1:4] = True
        scores = np.array([0.2, 0.9, 0.5][:count])
        index = int(np.argmax(scores))
        return SegmentationResult(
            masks=masks, scores=scores, logits=None, selected_index=index,
            selected_mask=masks[index], selected_score=float(scores[index]),
            prompt_type="box", prompt_data={"box_xyxy": box}, image_shape=self.shape,
            model_name="sam2.1_hiera_small", model_config="synthetic", checkpoint_name="fake.pt",
            device="cpu", dtype="float32", load_time_seconds=0, embedding_time_seconds=0.05,
            prediction_time_seconds=0.01, peak_vram_bytes=None,
        )

    def clear_image(self):
        self.calls.append("clear")
        self.embedding_time_seconds = None

    def close(self):
        self.calls.append("close")


def run_fake(enid, **kwargs):
    return run_robustness(**enid, device="cpu", segmenter_factory=FakeSegmenter, **kwargs)


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def test_expand_math_on_known_box():
    box = (10.0, 20.0, 40.0, 30.0)
    assert perturb_box(box, 1000, 1000, BY_NAME["expand10"], 0)[0] == pytest.approx((6, 17, 54, 53))
    assert perturb_box(box, 1000, 1000, BY_NAME["expand20"], 0)[0] == pytest.approx((2, 14, 58, 56))
    assert perturb_box(box, 1000, 1000, BY_NAME["ref"], 0) == ((10, 20, 50, 50), False)


def test_clipping_to_image_bounds_is_flagged():
    box, clipped = perturb_box((1.0, 1.0, 10.0, 10.0), 12, 12, BY_NAME["expand20"], 0)
    assert clipped and box == (0.0, 0.0, 12.0, 12.0)
    box, clipped = perturb_box((4.0, 4.0, 2.0, 2.0), 12, 12, BY_NAME["expand20"], 0)
    assert not clipped and box == pytest.approx((3.6, 3.6, 6.4, 6.4))


def test_jitter_is_deterministic_bounded_and_order_independent():
    bbox, width, height, condition = (100.0, 50.0, 40.0, 20.0), 1000, 1000, BY_NAME["jitter10"]
    ids = list(range(200))
    forward = {aid: perturb_box(bbox, width, height, condition, aid) for aid in ids}
    backward = {aid: perturb_box(bbox, width, height, condition, aid) for aid in reversed(ids)}
    assert forward == backward
    original = np.array([100, 50, 140, 70])
    shifts = np.array([box for box, _ in forward.values()]) - original
    limits = np.array([4, 2, 4, 2])  # 10% of w=40 (x) and h=20 (y)
    assert (np.abs(shifts) <= limits).all() and (np.abs(shifts) > 0).all()
    assert len({box for box, _ in forward.values()}) == len(ids)
    other_seed = perturb_box(bbox, width, height, condition, 0, seed=SEED + 1)
    assert other_seed != forward[0]


def test_degenerate_perturbation_fails_explicitly(enid):
    shrink = Condition("shrink60", True, "expand", -0.6)
    with pytest.raises(ValueError, match="Degenerate shrink60 box for annotation 7"):
        perturb_box((10.0, 10.0, 10.0, 10.0), 100, 100, shrink, 7)
    wild = Condition("jitter60", True, "jitter", 0.6)
    failures = 0
    for aid in range(200):
        try:
            box, _ = perturb_box((10.0, 10.0, 10.0, 10.0), 100, 100, wild, aid)
            assert box[2] > box[0] and box[3] > box[1]
        except ValueError as exc:
            assert "Degenerate jitter60" in str(exc)
            failures += 1
    assert failures > 0
    created = len(FakeSegmenter.instances)
    with pytest.raises(RuntimeError, match="prompt_validation.*Degenerate"):
        run_fake(enid, conditions=(*CONDITIONS, shrink))
    assert len(FakeSegmenter.instances) == created  # failed before the model was built
    summary = json.loads((enid["output"] / "summary.json").read_text())
    assert summary["status"] == "incomplete" and summary["rows_written"] == 0


def test_one_row_per_annotation_condition_and_one_embedding_per_image(enid):
    summary = run_fake(enid)
    fake = FakeSegmenter.instances[-1]
    assert summary["status"] == "complete" and summary["rows_written"] == 4 * len(CONDITIONS)
    assert fake.calls == ["load", "set", "clear", "set", "clear", "set", "clear", "close"]
    rows = read_csv(enid["output"] / "results_long.csv")
    keys = [(int(r["annotation_id"]), r["condition"]) for r in rows]
    assert keys == [(aid, c.name) for aid in range(4) for c in CONDITIONS]
    assert [multi for _, multi in fake.prompts] == [c.multimask_output for c in CONDITIONS] * 4
    for row in rows:
        expected = 0 if row["condition"] == "ref_single" else 1
        assert int(row["selected_index"]) == expected
    samples = {s.annotation_id: s for s in load_samples(enid["dataset_root"], enid["split_root"])}
    for row in rows:
        sample, condition = samples[int(row["annotation_id"])], BY_NAME[row["condition"]]
        box, clipped = perturb_box(sample.bbox_xywh, sample.width, sample.height, condition, sample.annotation_id)
        recorded = tuple(float(row[k]) for k in ("prompt_x_min", "prompt_y_min", "prompt_x_max", "prompt_y_max"))
        assert recorded == box and row["clipped"] == str(clipped)
    # Annotation 1 touches the image corner, so expansion is clipped; ref never is.
    clipped = {(int(r["annotation_id"]), r["condition"]) for r in rows if r["clipped"] == "True"}
    assert {(1, "expand10"), (1, "expand20")} <= clipped and not any(c[1].startswith("ref") for c in clipped)
    # Reference polygons equal their bboxes: original prompts reproduce the filled-box baseline exactly.
    assert all(float(r["prompt_box_dice"]) == 1 for r in rows if r["condition"] == "ref")
    timing = read_csv(enid["output"] / "image_timing.csv")
    assert [int(r["image_id"]) for r in timing] == [0, 1, 2]
    assert all(float(r["embedding_time_seconds"]) == 0.05 for r in timing)
    assert summary["by_condition"]["ref"]["count"] == 4 and summary["gpu"] is None
    assert summary["seed"] == SEED and len(summary["checkpoint_sha256"]) == 64
    assert not list(enid["output"].glob("*.incomplete.csv"))


def test_failure_keeps_explicit_incomplete_outputs(enid, monkeypatch):
    monkeypatch.setattr(FakeSegmenter, "fail_at", 7)  # second annotation, second condition
    with pytest.raises(RuntimeError, match="annotation=1, condition=ref_single"):
        run_fake(enid)
    summary = json.loads((enid["output"] / "summary.json").read_text())
    assert summary["status"] == "incomplete" and summary["failure"]["condition"] == "ref_single"
    assert (enid["output"] / "results_long.incomplete.csv").exists()
    assert not (enid["output"] / "results_long.csv").exists()
    assert FakeSegmenter.instances[-1].calls[-2:] == ["clear", "close"]


def test_nonempty_output_is_rejected(enid):
    enid["output"].mkdir()
    (enid["output"] / "keep.txt").write_text("existing")
    with pytest.raises(ValueError, match="empty"):
        run_fake(enid)
    assert [p.name for p in enid["output"].iterdir()] == ["keep.txt"]


def test_checkpoint_hash_mismatch_cli_nonzero(enid, capsys, monkeypatch):
    monkeypatch.setattr("experiments.benchmarks.enid.robustness.SAM2Segmenter", FakeSegmenter)
    args = [f"--{k.replace('_', '-')}={v}" for k, v in enid.items()]
    assert main([*args, "--device=cpu", "--expected-checkpoint-sha256=" + "0" * 64]) == 1
    assert "does not match" in capsys.readouterr().err


@pytest.mark.parametrize("box", [
    (0.0, 0.0, 3.0, 2.0), (1.3, 0.7, 6.9, 5.2), (0.25, 2.75, 9.0, 7.0),
    (2.1, 0.0, 9.0, 4.4), (5.5, 3.25, 10.0, 8.0), (0.0, 0.0, 10.0, 8.0),
])
def test_prompt_rasterization_matches_direct_polygon(enid, box):
    # Fractional and border-touching XYXY prompts must not change pixels through XYWH conversion.
    sample = load_samples(enid["dataset_root"], enid["split_root"])[3]  # 10x8 image
    x0, y0, x1, y1 = box
    rles = coco_mask.frPyObjects([[x0, y0, x1, y0, x1, y1, x0, y1]], sample.height, sample.width)
    direct = coco_mask.decode(coco_mask.merge(rles)).astype(bool)
    assert np.array_equal(prompt_box_mask(sample, box, original=False), direct)
    assert np.array_equal(prompt_box_mask(sample, (1, 1, 4, 4), original=True), box_mask(sample))

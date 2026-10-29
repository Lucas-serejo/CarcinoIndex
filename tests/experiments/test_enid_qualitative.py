import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from experiments.analysis.enid import qualitative as q
from experiments.benchmarks.enid.dataset import load_samples, overlap_metrics, reference_mask
from scripts.render_enid_qualitative_cases import main


@pytest.fixture
def research(tmp_path):
    root, splits = tmp_path / "dataset", tmp_path / "splits"
    (root / "frames").mkdir(parents=True)
    splits.mkdir()
    images = [dict(id=i, file_name=f"c_{i}_frame.png", width=10, height=8) for i in (1, 2)]
    annotations = [dict(id=aid, image_id=iid, category_id=1, bbox=[aid, 1, 2, 2],
                        segmentation=[[aid, 1, aid+2, 1, aid+2, 3, aid, 3]])
                   for aid, iid in ((1, 1), (2, 2), (3, 1))]
    data = dict(images=images, annotations=annotations)
    (root / "coco.json").write_text(json.dumps(data))
    for name in ("train", "val", "test"):
        (splits / f"coco_{name}.json").write_text(json.dumps(
            data if name == "train" else dict(images=[], annotations=[])))
    for image in images:
        Image.new("RGB", (10, 8), (40, 70, 90)).save(root / "frames" / image["file_name"])
    # Deliberately unrelated raster annotation: the renderer must ignore it.
    (root / "annots").mkdir()
    Image.new("L", (10, 8), 255).save(root / "annots" / "c_1_frame.png")
    predictions, rows = {}, []
    for sample in load_samples(root, splits):
        prediction = reference_mask(sample).copy()
        prediction[0, 0] = True
        predictions[sample.annotation_id] = prediction
        rows.append(dict(dataset="ENID", annotation_id=sample.annotation_id,
                         image_id=sample.image_id, file_name=sample.file_name,
                         split=sample.split, group_id=sample.group_id, width=10, height=8,
                         **dict(zip(("bbox_x", "bbox_y", "bbox_width", "bbox_height"), sample.bbox_xywh)),
                         **overlap_metrics(prediction, reference_mask(sample)),
                         selected_index=1, selected_score=0.8, prediction_time_seconds=0.01))
    results, cases, checkpoint = (tmp_path / name for name in ("results.csv", "extremes.csv", "fake.pt"))
    pd.DataFrame(rows).to_csv(results, index=False)
    # Reversed source order must not change the verified selection or output order.
    q.extreme_cases(q.load_results(results)).iloc[::-1].to_csv(cases, index=False)
    checkpoint.write_bytes(b"synthetic checkpoint")

    class Fake:
        calls = []
        score = 0.80000001
        index = 1

        def __init__(self, **kwargs):
            assert kwargs["device"] == "cpu"

        def load(self):
            self.calls.append("load")

        def set_image(self, image):
            assert image.shape == (8, 10, 3) and image.dtype == np.uint8
            assert tuple(image[0, 0]) == (40, 70, 90)
            self.calls.append("set")

        def segment_with_box(self, box, multimask_output):
            aid = int(box[0])
            assert box == (aid, 1, aid+2, 3) and multimask_output is True
            self.calls.append(aid)
            return SimpleNamespace(selected_mask=predictions[aid], selected_index=self.index,
                                   selected_score=self.score,
                                   masks=np.zeros((3, 8, 10), dtype=bool))

        def clear_image(self):
            self.calls.append("clear")

        def close(self):
            self.calls.append("close")

    return dict(dataset_root=root, split_root=splits, results=results, cases=cases,
                checkpoint=checkpoint, output=tmp_path / "output", device="cpu",
                segmenter_factory=Fake)


def rewrite(path, change):
    frame = pd.read_csv(path)
    frame = change(frame)
    frame.to_csv(path, index=False)


def test_artifacts_provenance_and_lifecycle(research, monkeypatch):
    inputs = {p: p.read_bytes() for p in research["results"].parent.rglob("*") if p.is_file()}
    calls = []
    original = q.overlap_metrics

    def measured(prediction, reference):
        calls.append((prediction.copy(), reference.copy()))
        return original(prediction, reference)

    monkeypatch.setattr(q, "overlap_metrics", measured)
    manifest = q.render_cases(**research)
    assert manifest["status"] == "complete"
    assert manifest["selection_rows"] == 9 and manifest["unique_annotations_rendered"] == 3
    assert manifest["selected_annotation_ids"] == [1, 2, 3]
    assert research["segmenter_factory"].calls == ["load", "set", 1, 3, "clear", "set", 2, "clear", "close"]
    output = research["output"]
    frame = pd.read_csv(output / "cases.csv")
    assert frame.annotation_id.tolist() == [1, 2, 3]
    assert json.loads(frame.iloc[0].selection_reasons) == [
        "highest_dice", "largest_predicted_reference_area_ratio", "lowest_dice"]
    assert json.loads(frame.iloc[0].selection_ranks) == [1, 1, 1]
    assert (frame.dice_abs_delta == 0).all() and (frame.iou_abs_delta == 0).all()
    assert (frame.selected_score_abs_delta > 0).all()
    for row, (prediction, reference) in zip(frame.to_dict("records"), calls):
        assert reference.sum() == 4
        assert row["benchmark_predicted_area_pixels"] == 5
        assert row["rerun_predicted_area_pixels"] == int(prediction.sum()) == 5
        assert row["predicted_area_pixel_delta"] == 0
        for key in ("comparison_path", "reference_mask_path", "sam_mask_path"):
            assert not Path(row[key]).is_absolute()
            assert (output / row[key]).stat().st_size > 0
        for key, expected in (("reference_mask_path", reference), ("sam_mask_path", prediction)):
            with Image.open(output / row[key]) as mask:
                assert mask.mode == "L" and mask.size == (10, 8)
                assert set(np.unique(mask)) == {0, 255}
                np.testing.assert_array_equal(np.asarray(mask), expected.astype(np.uint8) * 255)
    for name, path in [("results.csv", research["results"]), ("extreme_cases.csv", research["cases"]),
                       ("checkpoint", research["checkpoint"]), ("coco.json", research["dataset_root"] / "coco.json"),
                       *[(f"coco_{s}.json", research["split_root"] / f"coco_{s}.json") for s in q.SPLITS]]:
        assert manifest["sha256"][name] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert str(output.parent) not in json.dumps(manifest)
    assert manifest["multimask_output"] is True
    assert manifest["rerun_metric_tolerance"] == 1e-6
    assert all(path.read_bytes() == content for path, content in inputs.items())


@pytest.mark.parametrize("column", ["annotation_id", *q.IDENTITY, "selection_reason", "rank"])
def test_required_cases_columns(research, column):
    rewrite(research["cases"], lambda f: f.drop(columns=column))
    with pytest.raises(ValueError, match="Missing cases columns"):
        q.render_cases(**research)


@pytest.mark.parametrize("field,value", [("rank", 0), ("rank", 1.5), ("rank", np.inf),
    ("selection_reason", "visual_choice"), ("image_id", 99), ("group_id", "c_99"),
    ("file_name", "other.png"), ("split", "test"), ("annotation_id", 99)])
def test_invalid_cases(research, field, value):
    rewrite(research["cases"], lambda f: f.assign(**{field: value}))
    with pytest.raises(ValueError):
        q.render_cases(**research)


@pytest.mark.parametrize("alteration", ["annotation", "reason", "rank", "missing", "extra"])
def test_altered_quantitative_selection_fails_before_outputs(research, alteration):
    frame = pd.read_csv(research["cases"])
    if alteration == "annotation":
        # Substitute a valid benchmark annotation, including its matching identity.
        replacement = pd.read_csv(research["results"]).iloc[0]
        for field in ("annotation_id", *q.IDENTITY):
            frame.loc[0, field] = replacement[field]
    elif alteration == "reason":
        frame.loc[0, "selection_reason"] = "smallest_predicted_reference_area_ratio"
    elif alteration == "rank":
        frame.loc[0, "rank"] = 99
    elif alteration == "missing":
        frame = frame.iloc[1:]
    else:
        frame = pd.concat([frame, frame.iloc[:1]])
    frame.to_csv(research["cases"], index=False)
    with pytest.raises(ValueError, match="deterministic quantitative selection"):
        q.render_cases(**research)
    assert not research["output"].exists()
    assert research["segmenter_factory"].calls == []


@pytest.mark.parametrize("column", ["dice", "iou", "reference_area_pixels", "predicted_area_pixels",
                                    "selected_index", "selected_score"])
@pytest.mark.parametrize("invalid", ["missing", "nan"])
def test_required_benchmark_metrics(research, column, invalid):
    rewrite(research["results"], lambda f: f.drop(columns=column) if invalid == "missing"
            else f.assign(**{column: np.nan}))
    with pytest.raises(ValueError):
        q.render_cases(**research)


def test_duplicate_results(research):
    rewrite(research["results"], lambda f: pd.concat([f, f.iloc[:1]]))
    with pytest.raises(ValueError, match="unique"):
        q.render_cases(**research)


def test_missing_canonical_annotation(research):
    for path in [research["dataset_root"] / "coco.json", research["split_root"] / "coco_train.json"]:
        data = json.loads(path.read_text())
        data["annotations"] = [a for a in data["annotations"] if a["id"] != 3]
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="missing from canonical"):
        q.render_cases(**research)


@pytest.mark.parametrize("field,delta", [("dice", 0.5e-6), ("iou", 0.5e-6),
    ("dice", 2e-6), ("iou", 2e-6), ("selected_index", 1), ("predicted_area_pixels", 1)])
def test_consistency(research, field, delta):
    rewrite(research["results"], lambda f: f.assign(**{field: f[field] + delta}))
    if delta < q.TOLERANCE:
        assert q.render_cases(**research)["status"] == "complete"
    else:
        with pytest.raises(ValueError, match="consistency mismatch"):
            q.render_cases(**research)
        manifest = json.loads((research["output"] / "manifest.json").read_text())
        assert manifest["status"] == "incomplete"
        assert not (research["output"] / "cases.csv").exists()
        assert research["segmenter_factory"].calls[-1] == "close"


def test_nonempty_output(research):
    research["output"].mkdir()
    existing = research["output"] / "existing"
    existing.write_text("keep")
    with pytest.raises(ValueError, match="must be empty"):
        q.render_cases(**research)
    assert existing.read_text() == "keep"


def test_empty_output_and_dimensions(research):
    research["output"].mkdir()
    Image.new("RGB", (11, 8)).save(research["dataset_root"] / "frames" / "c_1_frame.png")
    with pytest.raises(ValueError, match="dimensions"):
        q.render_cases(**research)


def test_canonical_identity(research):
    for key in ("results", "cases"):
        rewrite(research[key], lambda f: f.assign(group_id="c_99"))
    with pytest.raises(ValueError, match="Canonical identity"):
        q.render_cases(**research)


def test_cli_error(research):
    args = []
    for key in ("dataset_root", "split_root", "results", "cases", "checkpoint", "output"):
        args.extend(["--" + key.replace("_", "-"), str(research[key])])
    research["cases"].write_text("invalid\n")
    assert main(args) == 1


@pytest.fixture
def saved_artifacts(research, monkeypatch):
    # Produce the existing scientific contract using synthetic masks only.
    monkeypatch.setattr(q, "_comparison", lambda *args: None)
    q.render_cases(**research)
    research["segmenter_factory"].calls.clear()
    return {key: research[key] for key in ("dataset_root", "split_root", "results", "cases")} | {
        "source": research["output"], "output": research["output"].parent / "localized"}


def test_render_only_preserves_sources_and_reuses_exact_masks(saved_artifacts, monkeypatch):
    from experiments.analysis.enid import render_only as ro
    source = saved_artifacts["source"]
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    calls = []
    def draw(path, rgb, reference, prediction, sample, record, language):
        assert language == "pt-BR"
        for mask, name in ((reference, "reference_mask"), (prediction, "sam_mask")):
            with Image.open(source / "cases" / f"annotation_{sample.annotation_id:06d}" / f"{name}.png") as image:
                np.testing.assert_array_equal(mask, np.asarray(image) == 255)
        assert record["selected_score"] == .8 and record["selected_index"] == 1
        calls.append(sample.annotation_id)
    monkeypatch.setattr(ro, "_comparison", draw)
    manifest = ro.render_existing(**saved_artifacts)
    assert calls == [1, 2, 3]
    assert manifest["status"] == "complete" and manifest["inference_executed"] is False
    assert manifest["mode"] == "render-only" and len(manifest["source_mask_sha256"]) == 6
    assert manifest["source_directory"] == source.name
    assert str(source.parent) not in (saved_artifacts["output"] / "manifest.json").read_text(encoding="utf-8")
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not (saved_artifacts["output"] / "cases.csv").exists()


@pytest.mark.parametrize("damage", ["incomplete", "manifest_ids", "hash", "policy", "missing_mask", "binary",
    "dimensions", "reference", "prediction", "case_id", "case_order", "bbox", "index", "score", "dice",
    "reference_area", "prediction_area", "reasons", "path", "image_dimensions"])
def test_render_only_fails_before_creating_output(saved_artifacts, damage):
    from experiments.analysis.enid.render_only import render_existing
    source = saved_artifacts["source"]
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    rows = pd.read_csv(source / "cases.csv")
    mask = source / rows.iloc[0].sam_mask_path
    if damage == "incomplete": manifest["status"] = "incomplete"
    elif damage == "manifest_ids": manifest["selected_annotation_ids"] = [1, 2]
    elif damage == "hash": manifest["sha256"]["results.csv"] = "invalid"
    elif damage == "policy": manifest["selection_policy"] = "best Dice"
    elif damage == "missing_mask": mask.unlink()
    elif damage == "binary": Image.new("L", (10, 8), 1).save(mask)
    elif damage == "dimensions": Image.new("L", (11, 8)).save(mask)
    elif damage == "reference": Image.new("L", (10, 8)).save(source / rows.iloc[0].reference_mask_path)
    elif damage == "prediction": Image.new("L", (10, 8)).save(mask)
    elif damage == "case_id": rows.loc[0, "annotation_id"] = 9
    elif damage == "case_order": rows = rows.iloc[::-1]
    elif damage == "bbox": rows.loc[0, "bbox_x"] = 9
    elif damage == "index": rows.loc[0, "rerun_selected_index"] = 2
    elif damage == "score": rows.loc[0, "benchmark_selected_score"] = .9
    elif damage == "dice": rows.loc[0, "benchmark_dice"] = .1
    elif damage == "reference_area": rows.loc[0, "reference_area_pixels"] = 9
    elif damage == "prediction_area": rows.loc[0, "benchmark_predicted_area_pixels"] = 9
    elif damage == "reasons": rows.loc[0, "selection_reasons"] = '[]'
    elif damage == "path": rows.loc[0, "sam_mask_path"] = '../outside.png'
    elif damage == "image_dimensions": Image.new("RGB", (11, 8)).save(saved_artifacts["dataset_root"] / "frames" / "c_1_frame.png")
    manifest_path.write_text(json.dumps(manifest))
    rows.to_csv(source / "cases.csv", index=False)
    with pytest.raises((ValueError, OSError)):
        render_existing(**saved_artifacts)
    assert not saved_artifacts["output"].exists()


def test_render_only_refuses_source_and_existing_output(saved_artifacts):
    from experiments.analysis.enid.render_only import render_existing
    for output in (saved_artifacts["source"], saved_artifacts["source"] / "new", saved_artifacts["dataset_root"] / "new"):
        with pytest.raises(ValueError, match="outside source"):
            render_existing(**(saved_artifacts | {"output": output}))
    saved_artifacts["output"].mkdir()
    with pytest.raises(ValueError, match="new directory"):
        render_existing(**saved_artifacts)


def test_comparison_localization_preserves_geometry_and_artists(research, tmp_path, monkeypatch):
    from experiments.analysis.enid import rendering
    original_save = rendering.Figure.savefig
    captured = []
    def save(figure, *args, **kwargs):
        original_save(figure, *args, **kwargs)
        captured.append([(axis.get_position().bounds, axis.get_xlim(), axis.get_ylim(),
                          [image.get_array().copy() for image in axis.images], axis.get_title()) for axis in figure.axes])
    monkeypatch.setattr(rendering.Figure, "savefig", save)
    sample = load_samples(research["dataset_root"], research["split_root"])[0]
    reference = reference_mask(sample)
    record = q.load_results(research["results"]).iloc[0].to_dict()
    for language in ("en", "pt-BR"):
        rendering._comparison(tmp_path / f"{language}.png", np.zeros((8, 10, 3), dtype=np.uint8),
                              reference, reference, sample, record, language)
    for english, portuguese in zip(*captured):
        for a, b in zip(english[:3], portuguese[:3]): np.testing.assert_allclose(a, b, atol=1e-10, rtol=0)
        for a, b in zip(english[3], portuguese[3]): np.testing.assert_array_equal(a, b)
        assert english[4] != portuguese[4]
    assert captured[1][0][4] == "A. Imagem original + caixa delimitadora de referência"

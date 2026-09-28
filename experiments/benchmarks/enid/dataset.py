"""Canonical COCO annotations and official ENID split membership."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pycocotools import mask as coco_mask

SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class Sample:
    annotation_id: int
    image_id: int
    group_id: str
    file_name: str
    width: int
    height: int
    bbox_xywh: tuple[float, ...]
    segmentation: list[list[float]]
    split: str


def group_id(file_name: str) -> str:
    match = re.match(r"^(c_\d+)_", file_name)
    if not match:
        raise ValueError("ENID file_name must start with c_<number>_.")
    return match.group(1)


def xywh_to_xyxy(bbox: tuple[float, ...]) -> tuple[float, ...]:
    x, y, width, height = bbox
    return x, y, x + width, y + height


def read_coco(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read {path.name}; check dataset/split root.") from exc
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid JSON in {path.name}.") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid COCO object in {path.name}.")
    for key in ("images", "annotations"):
        entries = data.get(key)
        if not isinstance(entries, list) or any(
            not isinstance(item, dict) or type(item.get("id")) is not int
            for item in entries
        ):
            raise ValueError(f"Invalid COCO {key} in {path.name}.")
        if len({item["id"] for item in entries}) != len(entries):
            raise ValueError(f"Duplicate {key} IDs in {path.name}.")
    return data


def _numbers(values: object, label: str) -> np.ndarray:
    if not isinstance(values, list) or any(type(v) not in (int, float) for v in values):
        raise ValueError(f"{label} must contain numeric coordinates.")
    result = np.asarray(values, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"{label} must contain finite coordinates.")
    return result


def load_samples(dataset_root: Path, split_root: Path, split: str = "all",
                 limit: int | None = None) -> list[Sample]:
    """Validate the complete manifests; select by ascending annotation ID."""
    if split not in ("all", *SPLITS):
        raise ValueError("split must be all, train, val, or test.")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("limit must be a positive integer.")
    canonical = read_coco(dataset_root / "coco.json")
    images = {item["id"]: item for item in canonical["images"]}
    annotations = {item["id"]: item for item in canonical["annotations"]}
    image_splits, annotation_splits, group_splits = {}, {}, {}
    for name in SPLITS:
        manifest = read_coco(split_root / f"coco_{name}.json")
        local_images = {item["id"] for item in manifest["images"]}
        for image in manifest["images"]:
            image_id = image["id"]
            if image_id not in images or image_id in image_splits:
                raise ValueError(f"Unknown or overlapping image ID {image_id} in splits.")
            if any(image.get(k) != images[image_id].get(k) for k in ("file_name", "width", "height")):
                raise ValueError(f"Split image {image_id} disagrees with canonical COCO.")
            image_splits[image_id] = name
        for annotation in manifest["annotations"]:
            aid = annotation["id"]
            iid = annotation.get("image_id")
            if aid not in annotations or aid in annotation_splits:
                raise ValueError(f"Unknown or overlapping annotation ID {aid} in splits.")
            if iid not in local_images or iid != annotations[aid].get("image_id"):
                raise ValueError(f"Invalid split association for annotation {aid}.")
            annotation_splits[aid] = name
    if set(image_splits) != set(images) or set(annotation_splits) != set(annotations):
        raise ValueError("Official splits must cover all canonical images and annotations.")

    for iid, image in images.items():
        width, height, filename = image.get("width"), image.get("height"), image.get("file_name")
        if any(type(v) is not int or v <= 0 for v in (width, height)):
            raise ValueError(f"Invalid dimensions for image {iid}.")
        if not isinstance(filename, str) or any(c in filename for c in ("/", "\\", ":")):
            raise ValueError(f"Image {iid} requires a relative ENID frame filename.")
        gid = group_id(filename)
        name = image_splits[iid]
        if group_splits.setdefault(gid, name) != name:
            raise ValueError(f"group_id {gid} overlaps official splits.")

    samples = []
    for aid, annotation in sorted(annotations.items()):
        try:
            iid = annotation.get("image_id")
            if type(iid) is not int or iid not in images:
                raise ValueError("unknown image_id")
            image = images[iid]
            width, height = image["width"], image["height"]
            if annotation.get("category_id") != 1 or annotation.get("iscrowd", 0) != 0:
                raise ValueError("expected category_id=1 and iscrowd=0")
            bbox = _numbers(annotation.get("bbox"), "bbox")
            if bbox.shape != (4,):
                raise ValueError("bbox requires four XYWH values")
            x, y, w, h = bbox
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                raise ValueError("bbox must have positive area and stay within image bounds")
            polygons = annotation.get("segmentation")
            if not isinstance(polygons, list) or not polygons:
                raise ValueError("segmentation must be a nonempty polygon list; RLE is unsupported")
            for polygon in polygons:
                coordinates = _numbers(polygon, "polygon")
                if len(coordinates) < 6 or len(coordinates) % 2:
                    raise ValueError("polygon requires at least three XY pairs")
                points = coordinates.reshape(-1, 2)
                if (points < 0).any() or (points > [width, height]).any():
                    raise ValueError("polygon coordinates exceed image bounds")
            name = annotation_splits[aid]
            if name != image_splits[iid]:
                raise ValueError("annotation and image splits disagree")
            samples.append(Sample(aid, iid, group_id(image["file_name"]),
                                  image["file_name"], width, height,
                                  tuple(float(v) for v in bbox), polygons, name))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid annotation {aid}: {exc}") from exc
    selected = [sample for sample in samples if split == "all" or sample.split == split]
    if not selected:
        raise ValueError("No annotations in the requested selection.")
    return selected[:limit]


def reference_mask(sample: Sample) -> np.ndarray:
    rles = coco_mask.frPyObjects(sample.segmentation, sample.height, sample.width)
    result = coco_mask.decode(coco_mask.merge(rles)).astype(bool)
    if not result.any():
        raise ValueError(f"Annotation {sample.annotation_id} rasterizes to an empty reference mask.")
    return result


def overlap_metrics(prediction: np.ndarray, reference: np.ndarray) -> dict:
    if prediction.dtype != bool or reference.dtype != bool:
        raise ValueError("Metrics require boolean masks.")
    if prediction.ndim != 2 or prediction.shape != reference.shape:
        raise ValueError("Prediction and reference must have identical HxW shapes.")
    predicted_area, reference_area = int(prediction.sum()), int(reference.sum())
    intersection = int(np.count_nonzero(prediction & reference))
    total = predicted_area + reference_area
    union = total - intersection
    return {
        "reference_area_pixels": reference_area,
        "predicted_area_pixels": predicted_area,
        "dice": 2 * intersection / total if total else 1.0,
        "iou": intersection / union if union else 1.0,
    }

"""Render a 2x2 illustrative ENID figure (reference contours and boxes) on CPU, without SAM."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.benchmarks.enid.dataset import load_samples, reference_mask  # noqa: E402

# Confirmed panels: A, B (one annotation) and C, D (three to five annotations).
EXPECTED_IMAGE_IDS = (72, 136, 79, 32)
DPI = 200
CONTOUR_PX, BOX_PX = 2.0, 1.5
# Okabe-Ito subset chosen for contrast against reddish endoscopic tissue.
COLORS = ("#56B4E9", "#F0E442", "#009E73", "#CC79A7", "#FFFFFF")
COUNT_WORDS = {1: "Uma anotação", 2: "Duas anotações", 3: "Três anotações",
               4: "Quatro anotações", 5: "Cinco anotações"}
SELECTION_RULE = {
    "area_definition": "área da referência = número de pixels da máscara rasterizada por "
                       "reference_mask (experiments/benchmarks/enid/dataset.py)",
    "single_annotation": "entre as 94 imagens com exatamente 1 anotação, ordenar pela distância "
                         "absoluta entre a área da lesão e a mediana dessas áreas (1154,5 px); "
                         "selecionar as 2 primeiras com group_id distintos",
    "multiple_annotations": "entre as 29 imagens com 3 a 5 anotações, calcular a mediana das áreas "
                            "das lesões de cada imagem; ordenar pela distância absoluta até a "
                            "mediana desses valores (481 px); selecionar as 2 primeiras cujo "
                            "group_id não se repete entre os 4 painéis",
    "tie_break": "menor image_id",
    "group_id": "prefixo c_<n> do file_name",
}


def px_to_pt(px: float) -> float:
    return px * 72 / DPI


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_images(by_image: dict, areas: dict) -> tuple[list[int], dict]:
    def closest(candidates, key, center, used_groups):
        chosen = []
        for image_id in sorted(candidates, key=lambda i: (abs(key(i) - center), i)):
            group = by_image[image_id][0].group_id
            if group not in used_groups:
                chosen.append(image_id)
                used_groups.add(group)
            if len(chosen) == 2:
                return chosen
        raise ValueError("Not enough distinct groups for the selection rule.")

    single = [i for i, items in by_image.items() if len(items) == 1]
    multi = [i for i, items in by_image.items() if 3 <= len(items) <= 5]
    single_area = lambda i: areas[by_image[i][0].annotation_id]  # noqa: E731
    multi_area = lambda i: float(np.median([areas[s.annotation_id] for s in by_image[i]]))  # noqa: E731
    single_median = float(np.median([single_area(i) for i in single]))
    multi_median = float(np.median([multi_area(i) for i in multi]))
    groups: set[str] = set()
    selected = closest(single, single_area, single_median, groups)
    selected += closest(multi, multi_area, multi_median, groups)
    stats = {"single_annotation_images": len(single), "single_annotation_median_area_px": single_median,
             "three_to_five_annotation_images": len(multi), "multi_annotation_median_area_px": multi_median}
    return selected, stats


def render(dataset_root: Path, split_root: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError(f"Output directory already exists; refusing to overwrite: {output}")
    coco_path = dataset_root / "coco.json"
    samples = load_samples(dataset_root, split_root)
    by_image = defaultdict(list)
    for sample in samples:
        by_image[sample.image_id].append(sample)
    masks = {s.annotation_id: reference_mask(s) for s in samples}
    areas = {aid: int(mask.sum()) for aid, mask in masks.items()}
    selected, stats = select_images(by_image, areas)
    if tuple(selected) != EXPECTED_IMAGE_IDS:
        raise ValueError(f"Selection rule produced {selected}, expected {list(EXPECTED_IMAGE_IDS)}.")

    fig, axes = plt.subplots(2, 2, figsize=(10, 7.0))
    panels = []
    for letter, image_id, ax in zip("ABCD", selected, axes.flat):
        items = by_image[image_id]
        image = Image.open(dataset_root / "frames" / items[0].file_name).convert("RGB")
        ax.imshow(np.asarray(image))
        for index, sample in enumerate(items):
            color = COLORS[index % len(COLORS)]
            ax.contour(masks[sample.annotation_id].astype(float), levels=[0.5], colors=[color],
                       linewidths=px_to_pt(CONTOUR_PX))
            x, y, w, h = sample.bbox_xywh
            ax.add_patch(Rectangle((x, y), w, h, fill=False, edgecolor=color,
                                   linewidth=px_to_pt(BOX_PX), linestyle=(0, (4, 2))))
        ax.set_title(f"{letter}. {COUNT_WORDS[len(items)]}", loc="left", fontsize=11)
        ax.set_axis_off()
        panels.append({"panel": letter, "image_id": image_id, "file_name": items[0].file_name,
                       "group_id": items[0].group_id, "split": items[0].split,
                       "annotation_ids": [s.annotation_id for s in items],
                       "reference_area_px": [areas[s.annotation_id] for s in items],
                       "colors": [COLORS[i % len(COLORS)] for i in range(len(items))]})
    handles = [Line2D([], [], color="0.2", linewidth=2, label="Contorno: segmentação de referência"),
               Line2D([], [], color="0.2", linewidth=1.5, linestyle=(0, (4, 2)),
                      label="Retângulo: caixa delimitadora")]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=10,
               title="Cores distintas identificam cada anotação na mesma imagem", title_fontsize=9)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    output.mkdir(parents=True)
    figure_path = output / "enid_examples.png"
    fig.savefig(figure_path, dpi=DPI)
    plt.close(fig)

    manifest = {
        "dataset": "ENID",
        "coco_json": coco_path.as_posix(),
        "coco_json_sha256": sha256_file(coco_path),
        "image_ids": list(selected),
        "selection_rule": SELECTION_RULE,
        "selection_statistics": stats,
        "panels": panels,
        "style": {"contour_px": CONTOUR_PX, "box_px": BOX_PX, "mask_fill": "nenhum",
                  "palette": "Okabe-Ito", "dpi": DPI},
        "figure": figure_path.name,
        "figure_sha256": sha256_file(figure_path),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = render(**vars(args))
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"ENID examples rendered for image_ids {manifest['image_ids']}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

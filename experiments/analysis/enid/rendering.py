"""Shared presentation only: no model loading or inference."""

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle
from .localization import localize_figure

COLORS = ("#009E73", "#0072B2", "#D55E00")
ALPHA = 0.5


def _comparison(path, rgb, reference, prediction, sample, benchmark, language="en"):
    figure = Figure(figsize=(12, 8), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 2).ravel()
    for axis, label in zip(axes, (
        "A. Original + reference bbox", "B. ENID reference segmentation",
        "C. SAM selected mask", "D. Mask agreement / disagreement",
    )):
        axis.imshow(rgb, interpolation="nearest")
        axis.set_title(label, fontsize=11)
        axis.set_axis_off()
    x, y, w, h = sample.bbox_xywh
    axes[0].add_patch(Rectangle((x, y), w, h, fill=False, edgecolor=COLORS[1], linewidth=1.5))
    from matplotlib.colors import to_rgba

    def overlay(axis, masks, colors):
        layer = np.zeros((*reference.shape, 4))
        for mask, color in zip(masks, colors):
            layer[mask] = to_rgba(color, ALPHA)
        axis.imshow(layer, interpolation="nearest")

    overlay(axes[1], [reference], [COLORS[1]])
    overlay(axes[2], [prediction], [COLORS[2]])
    overlay(axes[3], [reference & prediction, reference & ~prediction,
                      prediction & ~reference], COLORS)
    axes[3].legend(handles=[Patch(color=color, label=label) for color, label in
                           zip(COLORS, ("Both", "Reference only", "SAM only"))],
                   loc="lower center", fontsize=8, ncol=3)
    # Fix bounds after adding the rectangle: the complete original frame is retained.
    for axis in axes:
        axis.set_xlim(-0.5, sample.width - 0.5)
        axis.set_ylim(sample.height - 0.5, -0.5)
    figure.suptitle(
        f"ENID annotation {sample.annotation_id} | {sample.split} | "
        f"Benchmark Dice {benchmark['dice']:.3f}, IoU {benchmark['iou']:.3f} | "
        f"SAM selected score {benchmark['selected_score']:.3f}", fontsize=11)
    localize_figure(figure, language)
    figure.savefig(path, dpi=180)
    figure.clear()


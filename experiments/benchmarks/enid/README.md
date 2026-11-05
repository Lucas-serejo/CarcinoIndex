**Language:** English · [Português](README.pt-BR.md)

# Experiment A — ENID guided segmentation

Question: given a laparoscopic lesion located by a reference bounding box, how
similar is the SAM 2.1 Hiera Small mask to the reference segmentation provided
by ENID?

ENID is a laparoscopic proxy of **endometriosis** lesions, not peritoneal
carcinomatosis. The official bounding box is an **oracle/control prompt**: this
experiment measures segmentation with known localization, not detection. There
is no training, fine-tuning, LS classification, PCI, or claim of clinical
validation.

## Protocol

- Experimental unit: one annotation. `coco.json` is the canonical source of `bbox`
  and `segmentation`; `annots/*.png` is not used by the experiment.
- The three official JSONs define the split. IDs and groups must be disjoint and
  cover the canonical COCO. `group_id` is the `c_<n>` filename prefix; its
  clinical meaning is undocumented, so it is not called patient_id.
- The COCO XYWH bounding box becomes `[x, y, x + width, y + height]`, without
  padding or jitter.
- `pycocotools.mask.frPyObjects → merge → decode` rasterizes the union of the
  polygons at each image's original resolution. An empty rasterized reference
  mask is an error.
- Reuses `SAM2Segmenter`, `DEFAULT_MODEL_CONFIG` and `SegmentationResult`.
  RGB uint8 images are loaded without manual resizing. There is one `set_image`
  per frame, sequential prompts, and state cleanup when each frame finishes.
- `multimask_output=True`; uses exactly `selected_mask`, selected by the highest
  score predicted by SAM. The mask is never chosen by overlap with the
  reference. `selected_score` **is not clinical confidence**.
- Annotations are sorted by ascending ID, filtered by split, and `--limit N` is
  applied. The selected annotations are then grouped by image to reuse
  embeddings. Row order may differ from global ID order when IDs interleave.
- Dice = `2 * intersection / (prediction_area + reference_area)`;
  IoU = `intersection / union`, on boolean masks. Areas are pixel counts, never
  the COCO `area` field. An empty prediction against a non-empty reference
  yields zero. The metrics function defines 1 for two empty masks, but the
  runner rejects an empty reference.

## Running

Install `backend/requirements.txt` and set up SAM and the local checkpoint as in
[the existing guide](../../../docs/methodology/sam2_windows_setup.md).

Expected layout of the directories passed to `--dataset-root` and `--split-root`
(frames are read from `frames/` by the canonical COCO `file_name`):

```text
<dataset-root>/
  coco.json              # canonical COCO: bbox and segmentation
  frames/
    <file_name>          # one file per image in coco.json
<split-root>/
  coco_train.json
  coco_val.json
  coco_test.json
```

From the repository root (single-line command, also PowerShell-compatible):

```text
python scripts/run_enid_benchmark.py --dataset-root datasets/raw/enid/ENID_v1.0_dataset --split-root datasets/raw/enid_split/ENID_v1.0_dataset --checkpoint ../sam2/checkpoints/sam2.1_hiera_small.pt --output experiments/outputs/enid-smoke --split all --device cuda --dtype float32 --limit 3
```

`--split` accepts `all` (default), `train`, `val`, `test`. Removing `--limit`
runs the whole selection; the full benchmark is a step after implementation.
`--config` defaults to `DEFAULT_MODEL_CONFIG`; `--dtype` accepts `float32`
(default) and `bfloat16`. There is no automatic CUDA-to-CPU fallback.

Use a new/empty output directory for each run. Directories inside the inputs or
inside `datasets/raw`, as well as non-empty output directories, are rejected
during pre-validation, before the experimental outputs are initialized. These
errors exit the CLI with a non-zero code and a message on stderr, without
starting a benchmark run or generating new summary or result files. Datasets
and outputs stay local and ignored by Git.

- `results.csv`: one row per annotation, with IDs, split, group, relative
  filename, dimensions, bounding box, polygon count, areas, Dice/IoU, and SAM
  selection/timing. `prediction_time_seconds` is the prediction time measured by
  the wrapper, excluding the embedding.
- `summary.json`: status, UTC time, counts, selection, SHA-256 hashes of COCO,
  splits and checkpoint, model/config/device/dtype, package versions, selection
  policy, per-annotation means and medians (overall and by split), and total time,
  including validation, hashing, loading and inference. It is not a per-patient
  estimate.
- After the outputs are initialized, configuration, data or inference failures
  exit the CLI with a non-zero code and a message on stderr. The runner records
  an `incomplete` summary and keeps `results.incomplete.csv` when it was created;
  the CSV may contain only the header if no annotation finished. This record
  depends on the output remaining writable. Partial results are not results of a
  complete run. `failure_count` counts the fatal event (including configuration
  errors), `success_count` counts finished rows. `images_processed` counts images
  with at least one finished annotation. The summary identifies the
  stage/IDs/error type without persisting absolute paths.

Hashes and versions help reproduce a run; bit-for-bit equality across different
hardware, kernels and versions is not guaranteed. No PNGs, figures or clinical
reports are generated.

## Robustness to imprecise boxes

A separate experiment (`robustness.py`), with a new output directory, measures
how sensitive SAM is to imprecisely drawn boxes. For each annotation, with a
single `set_image` per image, it runs five conditions in this order:

| Condition | Prompt | `multimask_output` |
| --- | --- | --- |
| `ref` | original XYXY bounding box (identical to the benchmark) | `True` |
| `ref_single` | original bounding box (ablation; `selected_index` always 0) | `False` |
| `expand10` / `expand20` | each side expanded outward by 10% / 20% of the width (x) or height (y) | `True` |
| `jitter10` | each coordinate shifted by U[−10%, +10%] of the width (x) or height (y) | `True` |

The jitter uses `numpy.random.default_rng([20261027, annotation_id])`, so it does
not depend on execution order. Perturbed boxes are clipped to
`[0, width] × [0, height]` (`clipped` records the clipping); an inverted or empty
box is an error, validated before the model loads. Coordinates stay as floats.
Each row also includes `prompt_box_dice`/`prompt_box_iou`, from the prompt box
itself rasterized by `box_baseline.box_mask`. The `ref` condition reproduced
`enid-full-01/results.csv` exactly for the 358 annotations (areas, index, score,
Dice and IoU without differences).

```text
python scripts/run_enid_box_robustness.py --dataset-root datasets/raw/enid/ENID_v1.0_dataset --split-root datasets/raw/enid_split/ENID_v1.0_dataset --checkpoint ../sam2/checkpoints/sam2.1_hiera_small.pt --output experiments/outputs/enid-box-robustness --device cuda --dtype float32 --expected-checkpoint-sha256 6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38
```

The CLI accepts the same options as the benchmark: `--split` (`all` default,
`train`, `val`, `test`), `--limit N`, `--config` (default `DEFAULT_MODEL_CONFIG`)
and `--dtype` (`float32` default or `bfloat16`). `--expected-checkpoint-sha256`
is optional: if the checkpoint hash differs, the run aborts before reading the
dataset and loading the model, with an `incomplete` summary.

Outputs: `results_long.csv` (annotation × condition), `image_timing.csv`
(embedding per image) and `summary.json` (condition definitions, seed, versions,
the path of the pycocotools module in the execution environment, hashes, GPU and
per-condition means), with the same new-directory, incremental-write and
`complete`/`incomplete` status rules as the runner. The CPU analysis of these
results is in `experiments/analysis/enid/README.md`.

## Tests

```text
python -m pytest tests/experiments/test_enid_benchmark.py -q
python -m pytest tests/experiments/test_enid_robustness.py -q
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

Temporary synthetic fixtures and a fake returning `SegmentationResult` check
COCO, splits, rasterization, metrics, selection, lifecycle and failures. These
tests do not load `sam2`, a real checkpoint, a GPU, or the real ENID.

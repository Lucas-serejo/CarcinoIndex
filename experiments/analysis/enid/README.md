# ENID quantitative analysis

This CPU-only layer reads the `results.csv` from completed Experiment A. It
computes descriptive and exploratory annotation-level results for the TCC
results chapter. It does not load SAM, a checkpoint, images, COCO annotations,
the database, API, or frontend. No benchmark rerun or overlays are performed.
Only the existing numpy, pandas, and matplotlib dependencies are used.

## Run

From the repository root, in the project's Python environment (PowerShell):

```powershell
python scripts/analyze_enid_results.py `
  --results experiments/outputs/enid-full-01/results.csv `
  --output experiments/outputs/enid-analysis-01
```

The output directory is created if absent; an existing empty directory is also
accepted. A non-empty directory is rejected without overwriting its contents.
Use a new directory for each run. Invalid input is rejected before output files
are written. A failed write can leave partial artifacts; choose a new directory
after correcting the failure.

Generated outputs are local and ignored by Git when stored under
`experiments/outputs/`. An arbitrary external output path is not automatically
covered by this repository's ignore rules. Do not commit generated CSV/JSON/PNG
files, datasets, benchmark results, clinical images, or checkpoints.

## Input contract

Required columns:

```text
dataset split group_id image_id annotation_id file_name width height
reference_area_pixels predicted_area_pixels dice iou selected_index
selected_score prediction_time_seconds
```

At least one row is required, with unique integer-like annotation IDs and
integer-like image IDs. Dataset must be `ENID`; split must be `train`, `val`,
or `test`. Smoke runs and subsets are supported; no 358-row requirement exists.
Text fields must be nonempty; group IDs remain strings (including leading zeros).
All required numeric fields must parse and be finite. Dice and IoU must be in
[0, 1]; reference areas and integer-like image dimensions must be positive;
predicted areas, integer-like selected indices, and prediction times must be
nonnegative. Selected score only needs to be finite; it is not constrained to
[0, 1]. Derived area ratios must also be finite. Optional source columns,
including bbox and polygon columns, are retained in the candidate CSV.

## Analyses and artifacts

**Primary result:** spatial agreement between SAM-selected masks and ENID
reference masks, measured using the existing Dice and IoU values. These metrics
are consumed as supplied; they are not recomputed or changed.

**Secondary descriptive results:** distributions and official split summaries.
The split analysis is descriptive. SAM was frozen and not trained on the ENID
train split in this experiment. Split differences do not measure generalization
in the traditional trained-model sense.

**Exploratory analyses:** associations of SAM selected score and reference-mask
area with Dice. Pearson is the linear correlation on the raw values. Spearman
is Pearson on average ranks, including tied values, without SciPy. Correlations
are `null` in JSON and labelled undefined in figures when fewer than two rows
or either variable is constant. No p-values, significance tests, confidence
intervals, regression, or causal interpretations are produced.

| File | Definition |
| --- | --- |
| `descriptive_summary.json` | Row count, unique image/group counts, present split counts; mean, median, minimum, Q1, Q3, maximum for Dice, IoU, selected score and reference area; population standard deviation (`ddof=0`) for Dice/IoU; Pearson and Spearman for both exploratory associations. |
| `descriptive_by_split.csv` | Count and mean, median, Q1, Q3, minimum, maximum for Dice and IoU. Present splits appear in train/val/test order followed by overall. |
| `dice_distribution.csv` | Counts and percentages of all annotations in [0, 0.5), [0.5, 0.7), [0.7, 0.8), [0.8, 0.9), [0.9, 1.0]. The last bin includes 1.0. These are visualization bins, not clinical or methodological success thresholds. |
| `extreme_cases.csv` | Up to five annotations per selection reason: lowest Dice, highest Dice, smallest area ratio strictly below 1, largest area ratio strictly above 1. |
| `dice_distribution.png` | Annotation-level Dice histogram, 20 equal bins on [0, 1], dashed median. |
| `iou_distribution.png` | Corresponding annotation-level IoU histogram. |
| `selected_score_vs_dice.png` | Scatter with linear score axis and Pearson/Spearman annotations. |
| `reference_area_vs_dice.png` | Scatter with logarithmic area axis and Pearson/Spearman annotations. Pearson is labelled `Pearson (raw area)`; correlations still use raw area values/ranks, not log-transformed area. |

`descriptive_summary.json` also records `source.filename` (the input basename,
without an absolute path) and `source.sha256` (SHA-256 of the exact input CSV
bytes). The same byte snapshot is hashed and parsed. Changes to line endings,
row order, or other input bytes change the hash even if statistics are unchanged.

Quartiles use linear interpolation at positions `(n - 1) * q` in sorted values.
Standard deviation describes the supplied population of annotations, so it is
zero for one row. JSON uses sorted keys and rejects NaN/Infinity serialization.
Rows are sorted by annotation ID before computation, making statistics invariant
to input row order; source provenance still reflects the exact input bytes.
Figures use the non-interactive Agg canvas, fixed size and
styling. Identical environments yield reproducible artifacts; rendering and
floating-point details can vary across library/font versions.

Candidates use one row per selection reason, with ranks starting at 1 within
each reason: `lowest_dice`, `highest_dice`,
`smallest_predicted_reference_area_ratio` (ratios strictly below 1), and
`largest_predicted_reference_area_ratio` (ratios strictly above 1).
An annotation can therefore appear multiple times. Numeric
annotation ID ascending breaks all ties. Categories can contain fewer than five
rows, or none for area ratios. `area_ratio = predicted_area_pixels /
reference_area_pixels`; values below/above 1 indicate smaller/larger predicted
area than reference. Equal-area annotations are excluded from these two
categories. Area ratio alone does not establish segmentation correctness,
spatial containment, under-segmentation, or over-segmentation.
All required input fields, optional columns, area ratio,
selection reason and rank are available for later inspection.

The candidate list supports the separate qualitative renderer below; no cases
are labelled clinically good or bad.

## Interpretation limits

- ENID contains endometriosis lesions, not peritoneal carcinomatosis.
- The bbox is reference-derived/oracle: this is segmentation with known
  localization, not lesion detection.
- Selected score is an internal SAM quality/ranking estimate, not clinical
  confidence.
- One annotation is the analysis unit. Multiple annotations can belong to one
  image, and multiple images can share a group ID. Group ID clinical semantics
  are not established and it must not be interpreted as patient ID.
- The completed run's 358 annotations must not be described as 358 independent
  patients. This tool does not assume annotation independence for inference.
- Correlations are exploratory and do not establish causality. No clinical
  adequacy threshold, clinical LS prediction, automatic PCI, or clinical
  validation is claimed.

## Synthetic verification

```powershell
python -m pytest tests/experiments/test_enid_analysis.py -q
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

Tests use temporary synthetic CSV files and headless figures; no real ENID or
benchmark output is required.

## Qualitative inspection of selected extremes

The separate renderer recreates masks for **every unique annotation** supplied
by `extreme_cases.csv`. These are deliberately selected quantitative extremes,
not representative samples of all ENID. There is no interactive selection or
visual filtering. Duplicate annotation IDs trigger only one prediction and one
figure; all supplied reason/rank pairs (including repeated rows) are retained.
Pairs are sorted by reason then numeric rank and stored as aligned JSON arrays
in `selection_reasons` and `selection_ranks` in `cases.csv`.

```powershell
python scripts/render_enid_qualitative_cases.py `
  --dataset-root datasets/raw/enid/ENID_v1.0_dataset `
  --split-root datasets/raw/enid_split/ENID_v1.0_dataset `
  --results experiments/outputs/enid-full-01/results.csv `
  --cases experiments/outputs/enid-analysis-01/extreme_cases.csv `
  --checkpoint ../sam2/checkpoints/sam2.1_hiera_small.pt `
  --output experiments/outputs/enid-qualitative-01 `
  --device cuda `
  --dtype float32
```

`--model-config` defaults to `DEFAULT_MODEL_CONFIG`. Match the original run's
checkpoint, config, device and dtype. No dependency is added. Synthetic tests
run on CPU without SAM, CUDA, real ENID or a real checkpoint; actual rendering
requires the same SAM environment as the benchmark.

The renderer validates the authoritative results using the existing analysis
validator, including unique annotation IDs and finite metrics, areas, selected
index and selected score. Cases require annotation/image IDs, file name, split,
group ID, one of the four documented reasons, and a positive integer rank.
Every case must match results and canonical COCO identity. Canonical data and
official splits are validated by `load_samples(..., split="all")`.

Unique annotations and output rows are ordered by annotation ID. To reuse one
`set_image()` embedding per image, inference visits images in first occurrence
order and predicts their selected annotations in ascending ID order. Selected
results for later IDs are cached until their turn in global rendering order.
Images are dimension-checked and converted to RGB uint8 without resizing.
Canonical polygons provide reference masks; `annots/*.png` is never used.
The oracle/reference XYWH bbox is converted to XYXY; `multimask_output=True`
and exactly `result.selected_mask` preserve highest-SAM-score selection.
Reference overlap never chooses a SAM candidate. No post-processing is applied.

The rerun exists only to recreate masks for visualization. `results.csv` remains
the authoritative numerical record and is never overwritten. Existing
`overlap_metrics()` computes rerun Dice/IoU for provenance only. Absolute Dice
or IoU differences **greater than 1e-6**, or a different selected index, abort
the run. Canonical reference area must also match the benchmark. Both scores
and their absolute difference are recorded without requiring bit equality;
small floating-point score differences can occur. This adds no segmentation
metric and is not a second quantitative experiment.

Use a new directory under ignored `experiments/outputs/`. An absent or empty
directory is accepted; a non-empty directory is rejected. Dataset and split
directories are protected from output writes. Validation failures before output
creation leave no artifacts. Later failures leave an `incomplete` manifest and
possibly partial images: these must not be treated as a completed run. Correct
the issue and choose a new output directory.

| Artifact | Contract |
| --- | --- |
| `manifest.json` | Completion status, UTC timestamp, selection-row and rendered-annotation counts, sorted selected IDs, model/config, checkpoint basename, device/dtype, selection policy, tolerance, package versions, SHA-256 of both exact input CSV byte snapshots, canonical COCO, each official split JSON and checkpoint. No absolute paths or exception text. |
| `cases.csv` | One row per unique annotation: identity, all selection reasons/ranks, canonical XYWH bbox, benchmark reference/predicted areas, benchmark and rerun Dice/IoU/index/score, absolute metric/score deltas, and relative artifact paths. Written only after all figures pass consistency checks. |
| `cases/annotation_000001/comparison.png` | Four full-frame panels: original with official bbox, ENID reference overlay, SAM selected-mask overlay, and both/reference-only/SAM-only pixels with legend. The ID uses at least six digits solely for file ordering. |
| `cases/annotation_000001/reference_mask.png` and `sam_mask.png` | Original-dimension binary 8-bit masks: background 0, mask 255. No standalone original image is copied. |

Figures use the non-interactive Agg canvas, a fixed colorblind-conscious palette
(green for intersection, blue for reference-only, vermilion for SAM-only), and
0.5 overlay opacity throughout. Full image geometry and context are retained;
there is no bbox crop. Titles report factual benchmark values. Plot rendering
can vary across library/font versions; plot pixels are not tested for equality.
All generated images, masks and tables are local research artifacts, never
repository inputs. Do not commit these artifacts or checkpoints.

Scientific limits remain unchanged: ENID depicts endometriosis lesions, **not
peritoneal carcinomatosis**. Localization remains oracle/reference-derived,
not autonomous detection. Generated images are not clinical validation. Area
ratio extremes alone do not prove under-segmentation or over-segmentation.
Visual inspection may describe apparent error patterns but does not establish
causality. Selected score remains an internal SAM ranking/quality estimate,
not clinical confidence. This protocol makes no conclusions about real images
and does not prescribe a thesis interpretation or final figure subset.

```powershell
python -m pytest tests/experiments/test_enid_qualitative.py -q
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

CI should run only synthetic tests, never real ENID/SAM qualitative rendering.

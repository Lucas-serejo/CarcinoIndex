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

**Qualitative analysis is not part of this iteration.** The candidate list only
supports later visual inspection; no cases are labelled clinically good or bad.

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

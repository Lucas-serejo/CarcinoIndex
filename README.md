**Language:** English · [Português](README.pt-BR.md)

# CarcinoIndex

CarcinoIndex is an experimental human-in-the-loop platform for investigating
assisted segmentation of laparoscopic lesions in the context of peritoneal
carcinomatosis. Its current focus is SAM 2.1 Hiera Small with specialist prompts.

The system does not autonomously discover where a lesion is. The specialist
indicates the clinical object of interest; SAM turns that prompt into a
segmentation mask for subsequent quantitative research. Clinical lesion score
(LS) is supplied by the specialist and is never inferred by SAM.

Documentation is available in English and Portuguese; the thesis is written in
Portuguese.

## Research objective and limits

Evaluate to what extent SAM 2.1, conditioned on a known lesion location (a
bounding box), produces masks spatially consistent with reference segmentations
in laparoscopic images. The current benchmark uses ENID (endometriosis) as a
laparoscopic proxy; it is not clinical validation for peritoneal carcinomatosis.
This is a research objective, not a claim of clinical validation, diagnostic
performance, or LS prediction performance.

The repository uses two experiment labels:

- **Experiment A**: the offline technical benchmark on ENID, with reference
  bounding boxes as prompts and ENID reference segmentations as the comparison.
  This is the experiment evaluated in the TCC.
- **Experiment B**: a planned target-domain evaluation with laparoscopic
  peritoneal carcinomatosis images and specialist review of the CarcinoIndex
  segmentation and workflow. It has not been carried out yet.

Physical lesion size in centimeters is not directly recoverable from monocular
image pixels without calibration, a physical reference, or depth information.
Pixel area is not a physical measurement, and the current system implements
neither physical-size estimation nor depth estimation.

There are currently no accepted, validated, reference, or ground truth masks in
the product workflow. Visual review and Evaluation finalization do not turn a
SAM mask into a reference mask or establish any of these mask states.
SAM's `selected_score` is an internal predicted quality/ranking score,
not clinical confidence.

For the planned Experiment B, the implemented qualitative categories are `adequate`, `partially_adequate`, and `inadequate`; the broader study
protocol remains pending validation. Manual mask correction or reference-mask creation is
not required by the minimum current TCC protocol.

Automatic feature-based LS modelling is outside the current TCC scope and is not
implemented. No classifier exists, and no features are computed or persisted by
the current clinical workflow.

## Implemented MVP v1 workflow (F1-F4)

The Angular frontend and FastAPI backend support:

1. Experiment Setup: enter pseudonymous case and annotator codes, choose a PCI
   region or explicitly indicate it could not be determined, and upload a clinical image. The backend persists the case, image,
   and draft Evaluation.
2. Segmentation Workspace: retrieve the persisted image and draw a bounding box
   around the specialist-indicated lesion.
3. SAM 2.1 inference: generate a mask from the prompt and persist a
   SegmentationAttempt. Multiple attempts may be created; the frontend displays
   the latest result from the current session. With the mask visible, the specialist
   rates its visual/spatial quality as Adequate, Partially adequate, or Inadequate.
   No category is preselected; preparing a new box or rerunning clears the review.
4. Clinical Assessment: review the selected segmentation quality, manually supply clinical LS
   (0-3) or explicitly indicate it could not be determined, and finalize the Evaluation.
   Optional annotator confidence is available only when a clinical LS is supplied.
5. New evaluation: after finalization, return to a clean Setup without reloading.
   The annotator code remains editable and prefilled; language and loaded regions
   are preserved. The next submission creates a new case, image, and Evaluation.

For the planned Experiment B, the visible case code identifies an experimental
case, not a patient. Each photograph may be treated as a new case; no patient relationship is
inferred between images. The internal API/database name `anonymous_patient_code`
remains unchanged. Resetting the workflow does not alter previous persisted records.

The backend also accepts point prompts, but the current frontend uses bounding
boxes. New API finalizations require an explicit `clinical_ls` value (0–3 or null), `reviewed_attempt_id`,
and `segmentation_quality`. The reviewed attempt must belong to that Evaluation.
Quality is a human qualitative judgment of SAM output, not clinical validation,
ground truth, LS, or SAM confidence. PCI region and LS are supplied by the specialist
when determinable; neither is inferred by SAM. Null region and finalized null LS mean
undetermined. Confidence must be null when LS is null.

PostgreSQL and local storage preserve the pseudonymous ClinicalCase, exact
original validated image bytes and their SHA-256, Evaluation, segmentation
attempts, SAM masks, prompt data, SAM metadata, specialist clinical LS, and
optional confidence in that LS assessment, plus the reviewed attempt ID and human
segmentation quality. The data model is:

`ClinicalCase -> Image -> Evaluation -> SegmentationAttempt`

The stateless segmentation endpoint remains available separately. Backend PCI
composition helper uses manually supplied regional LS; the experimental workflow
does not calculate the complete PCI. There is no autonomous lesion detection,
automatic clinical LS classification, or autonomous diagnosis.

## Image-coordinate integrity

Static JPEG and PNG uploads are accepted only when orientation metadata is absent
or EXIF Orientation is normal (`1`). Orientations `2` through `8` and malformed or
unsupported orientation metadata are rejected with HTTP `422`
(`unsupported_image_orientation`). Normalize orientation before uploading such
an image.

The server never rotates, transposes, resizes, or recompresses uploaded images.
Stored bytes equal validated uploaded bytes, and SHA-256 hashes those exact
bytes. Rejecting display transformations preserves agreement between the
specialist's browser coordinates and the pixels supplied to SAM. See the
[image validation and storage contract](docs/experiment_lifecycle_api.md#image-storage-and-transactions).

## Repository layout

```text
backend/       FastAPI, SAM wrapper, persistence
frontend/      Angular Experiment Setup, Segmentation, and Clinical Assessment
docs/          API lifecycle, architecture, and research methodology
notebooks/     Synthetic SAM wrapper validation
scripts/       Development launcher, SAM environment/feasibility checks, ENID benchmark,
               robustness, analysis and figure CLIs (including render_enid_examples.py),
               evaluation CSV export, and local experiment data reset
tests/         CPU-compatible tests and opt-in PostgreSQL/CUDA integration tests
datasets/      Research data organization; clinical images are not versioned
experiments/   Offline benchmarks and local outputs; checkpoints are not versioned
```

## Prerequisites

The validated environment is described step by step in the
[SAM 2.1 Windows setup guide](docs/methodology/sam2_windows_setup.md). In summary,
from the repository root:

1. Python 3.11 (the version used by CI) in a virtual environment such as `.venv`.
2. Install PyTorch **before** the project requirements, because
   `backend/requirements.txt` does not pin `torch`/`torchvision` and a plain
   install may resolve a different (for example CPU-only) build:

   ```powershell
   python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
   python -m pip install -r backend/requirements.txt
   ```

3. Install the official [SAM 2 repository](https://github.com/facebookresearch/sam2)
   in editable mode from a clone outside this repository (`pip install -e .`
   in the clone; the guide uses `SAM2_BUILD_CUDA=0`). SAM 2 is not listed in
   `backend/requirements.txt`.
4. Download the external `sam2.1_hiera_small.pt` checkpoint and verify its
   SHA-256 (`Get-FileHash -Algorithm SHA256`); the validated value is
   `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38`.
   The model config is `configs/sam2.1/sam2.1_hiera_s.yaml`.

No checkpoint is downloaded automatically. Clinical images and checkpoints
must stay outside version control. The frontend additionally requires Node.js 24
(see the [frontend README](frontend/README.md)).

## Development and technical documentation

Run backend commands from the repository root.

- [Backend setup and execution](backend/README.md): PostgreSQL, existing Alembic
  migrations, local storage, SAM/CUDA settings, and the Windows development script.
- [Frontend setup and workflow](frontend/README.md): Angular development, tests,
  production build, and F1-F4 behavior.
- [Experiment lifecycle API](docs/experiment_lifecycle_api.md): create and retrieve
  resources, record segmentation attempts, and finalize an Evaluation.
- [Experiment B CSV export](backend/README.md#exportação-do-experimento-b-csv):
  read-only `python scripts/export_experiment_b.py`, one row per finalized Evaluation.
- [Local experiment data reset](backend/README.md#reset-dos-dados-experimentais-locais):
  dry-run by default; `--execute --confirm <database>` clears experiment tables and managed storage.
- [Persistence architecture](docs/architecture/experiment_persistence.md): data
  model, transaction boundaries, and storage limitations.
- [SAM inference contract](docs/architecture/sam2_inference_contract.md): one
  model instance, one worker, and serialized inference.
- [SAM 2.1 Windows setup](docs/methodology/sam2_windows_setup.md): validated
  Python/PyTorch/CUDA environment, SAM 2 installation, checkpoint and SHA-256.
- [LS protocol pending validation](docs/methodology/pci_protocol_pending_validation.md):
  manual LS storage and the protocol identifiers used until size criteria are validated.
- [ENID segmentation benchmark](experiments/benchmarks/enid/README.md): offline
  Experiment A, reference box prompts, COCO polygon masks, and Dice/IoU.
- [ENID quantitative analysis](experiments/analysis/enid/README.md): reproducible
  descriptive summaries and exploratory figures from completed benchmark CSVs.

CPU-compatible backend tests:

```powershell
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

PostgreSQL tests require a disposable database configured through
`TEST_DATABASE_URL`; they skip when it is absent. Real SAM integration tests
require an external checkpoint and CUDA. `notebooks/sam_validation.ipynb` and
`scripts/run_sam2_real_image.py` support synthetic/non-clinical exploration.

Authentication, mask editing/acceptance, bulk image/mask dataset export, automatic LS,
and a complete PCI frontend are outside the implemented MVP.

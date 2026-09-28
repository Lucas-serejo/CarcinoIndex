# CarcinoIndex

CarcinoIndex is an academic human-in-the-loop research prototype for supporting
Peritoneal Cancer Index (PCI) evaluation in laparoscopic images. Its current
primary focus is evaluating SAM 2.1 Hiera Small as a specialist-guided
segmentation tool for peritoneal lesions.

The system does not autonomously discover where a lesion is. The specialist
indicates the clinical object of interest; SAM turns that prompt into a
segmentation mask for subsequent quantitative research. Clinical lesion score
(LS) is supplied by the specialist and is never inferred by SAM.

Academic documentation and thesis writing are developed in Portuguese.

## Research objective and limits

Evaluate whether SAM 2.1 can adequately represent specialist-indicated peritoneal
lesions in laparoscopic images, producing masks suitable for quantitative analysis.
This is a research objective, not a claim of clinical validation, diagnostic
performance, or LS prediction performance.

Physical lesion size in centimeters is not directly recoverable from monocular
image pixels without calibration, a physical reference, or depth information.
Pixel area is not a physical measurement, and the current system implements
neither physical-size estimation nor depth estimation.

Specialist mask validation/refinement is the planned next scientific stage.
There are currently no accepted, validated, reference, or ground truth masks in
the product workflow. Visual review and Evaluation finalization do not establish
any of these mask states. SAM's selected score is an internal model estimate,
not clinical confidence.

Feature extraction helpers and notebooks are exploratory. Feature-versus-LS
modelling depends on an adequate clinically reviewed dataset and a defined
process for specialist-validated/corrected masks. No classifier is implemented,
and no features are computed or persisted by the current clinical workflow.

## Implemented MVP v1 workflow (F1-F4)

The Angular frontend and FastAPI backend support:

1. Experiment Setup: enter pseudonymous case and annotator codes, choose a PCI
   region, and upload a clinical image. The backend persists the case, image,
   and draft Evaluation.
2. Segmentation Workspace: retrieve the persisted image and draw a bounding box
   around the specialist-indicated lesion.
3. SAM 2.1 inference: generate a mask from the prompt and persist a
   SegmentationAttempt. Multiple attempts may be created; the frontend displays
   the latest result from the current session.
4. Clinical Assessment: visually review the result, manually supply clinical LS
   (0-3) and optional annotator confidence, and finalize the Evaluation.

The backend also accepts point prompts, but the current frontend uses bounding
boxes. Finalization requires clinical LS; the API does not require a segmentation
attempt before finalization. It does not select or validate a mask.

PostgreSQL and local storage preserve the pseudonymous ClinicalCase, exact
original validated image bytes and their SHA-256, Evaluation, segmentation
attempts, SAM masks, prompt data, SAM metadata, specialist clinical LS, and
optional annotator confidence. The data model is:

`ClinicalCase -> Image -> Evaluation -> SegmentationAttempt`

The stateless segmentation endpoint remains available separately. Backend PCI
composition uses manually supplied regional LS, but a complete multi-region PCI
frontend workflow is not implemented. There is no autonomous lesion detection,
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
backend/       FastAPI, SAM wrapper, experimental feature helpers, persistence
frontend/      Angular Experiment Setup, Segmentation, and Clinical Assessment
docs/          API lifecycle, architecture, and research methodology
notebooks/     Synthetic SAM checks and exploratory research notes
scripts/       Local development and SAM feasibility tools
tests/         CPU-compatible tests and opt-in PostgreSQL/CUDA integration tests
datasets/      Research data organization; clinical images are not versioned
experiments/   Offline benchmarks and local outputs; checkpoints are not versioned
```

## Development and technical documentation

Run backend commands from the repository root. Use the existing Python virtual
environment or create one and install `backend/requirements.txt`. The backend
uses the official [SAM 2 repository](https://github.com/facebookresearch/sam2)
installed in editable mode and an external `sam2.1_hiera_small.pt` checkpoint.
No checkpoint is downloaded automatically. Clinical images and checkpoints
must stay outside version control.

- [Backend setup and execution](backend/README.md): PostgreSQL, existing Alembic
  migrations, local storage, SAM/CUDA settings, and the Windows development script.
- [Frontend setup and workflow](frontend/README.md): Angular development, tests,
  production build, and F1-F4 behavior.
- [Experiment lifecycle API](docs/experiment_lifecycle_api.md): create and retrieve
  resources, record segmentation attempts, and finalize an Evaluation.
- [Persistence architecture](docs/architecture/experiment_persistence.md): data
  model, transaction boundaries, and storage limitations.
- [SAM inference contract](docs/architecture/sam2_inference_contract.md): one
  model instance, one worker, and serialized inference.
- [ENID segmentation benchmark](experiments/benchmarks/enid/README.md): offline
  Experiment A, reference box prompts, COCO polygon masks, and Dice/IoU.

CPU-compatible backend tests:

```powershell
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

PostgreSQL tests require a disposable database configured through
`TEST_DATABASE_URL`; they skip when it is absent. Real SAM integration tests
require an external checkpoint and CUDA. `notebooks/sam_validation.ipynb` and
`scripts/run_sam2_real_image.py` support synthetic/non-clinical exploration.

Authentication, mask editing/acceptance, dataset export, automatic LS, and a
complete PCI frontend are outside the implemented MVP.

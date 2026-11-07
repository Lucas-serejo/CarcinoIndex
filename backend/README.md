**Language:** English · [Português](README.pt-BR.md)

# CarcinoIndex backend

Experimental API for specialist-guided SAM 2.1 Hiera Small segmentation and manual
PCI composition. SAM produces a mask from box or point prompts; it does not
classify lesions. Clinical LS is always supplied by the specialist.
It may be null in Evaluations, including finalized ones when undetermined.
PCI region may also be null when undetermined; neither field is inferred by SAM.
New finalizations require `reviewed_attempt_id` and
`segmentation_quality` (`adequate`, `partially_adequate`, or `inadequate`) alongside
explicit `clinical_ls` (0–3 or null) and optional confidence in LS (null if LS is
null). The repository verifies attempt ownership; missing or foreign attempts
return safe HTTP 422 errors. Evaluation responses include both review fields.
Apply `python -m alembic upgrade head` for `0003_optional_clinical_context`;
legacy finalized rows retain null review fields. The specialist supplies PCI
region, LS, and the qualitative review of SAM output. This does not accept or
validate a mask as ground truth or calculate complete PCI.

## Configuration

Set before running:

```powershell
$env:SAM2_CHECKPOINT_PATH = "path\to\external\sam2.1_hiera_small.pt"
$env:SAM2_MODEL_CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"
$env:SAM2_DEVICE = "cuda"
$env:SAM2_DTYPE = "float32"
```

Optional settings:

```powershell
$env:MAX_UPLOAD_BYTES = "10485760"
$env:MAX_IMAGE_WIDTH = "4096"
$env:MAX_IMAGE_HEIGHT = "4096"
$env:MAX_IMAGE_PIXELS = "16000000"
$env:API_PREFIX = "/api/v1"
```

Persistence (required for the persisted routes):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/carcinoindex"
$env:STORAGE_ROOT = "storage"
```

`DATABASE_URL` must use the `postgresql+psycopg` driver. `STORAGE_ROOT` is
optional (default `storage`, resolved from the working directory). Without
`DATABASE_URL`, the API starts normally, but the persisted routes respond
`503` with the code `persistence_unavailable`; the stateless routes remain
available.

The checkpoint path is required for a real startup. There is no fallback to
CPU or to another model.

## Running

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app `
  --host 127.0.0.1 `
  --port 8000 `
  --workers 1
```

At this stage a single worker and one inference at a time are mandatory. The
model is loaded once in the lifespan and closed on shutdown.

Stateless routes (no database required):

- `GET /health`;
- `POST /api/v1/segmentations`;
- `GET /api/v1/pci/regions`;
- `POST /api/v1/pci/calculate`.

In these routes, static JPEG and PNG images are processed only in memory. The
application does not persist images, masks, prompts or results in these endpoints.

Persisted routes (require `DATABASE_URL`; see the
[lifecycle guide](../docs/experiment_lifecycle_api.md)):

- `POST /api/v1/cases`;
- `POST /api/v1/cases/{case_id}/images`;
- `GET /api/v1/images/{image_id}/content`;
- `POST /api/v1/images/{image_id}/evaluations`;
- `GET /api/v1/evaluations/{evaluation_id}`;
- `POST /api/v1/evaluations/{evaluation_id}/segmentations`;
- `POST /api/v1/evaluations/{evaluation_id}/finalize`.

Use is experimental and not intended for autonomous diagnosis.

## API documentation

- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- OpenAPI specification: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

## Windows development

With the Python and SAM/CUDA environment configured as above and Docker Desktop
running, prepare `.env` with `Copy-Item .env.example .env` and adjust the values.
Set `SAM2_CHECKPOINT_PATH` in `.env` to the local checkpoint path, kept outside
the repository; the provided path is only an example. For normal development,
run from the repository root:

```powershell
.\scripts\dev.ps1
```

The script refuses to run outside the repository root and requires `.env`. It
loads `.env` into the current process and, before starting Docker, checks that
`SAM2_CHECKPOINT_PATH` is set and points to an existing file. It then uses
`.venv\Scripts\python.exe` when available (otherwise `python` from PATH), starts
only PostgreSQL with `docker compose up -d --wait postgres`, and applies the
existing migrations with `python -m alembic upgrade head`. It does not create new
migrations. The loader accepts `NAME=value`, single or double outer quotes, blank
lines and comments starting with `#`; it does not expand variables or interpret
end-of-line comments.

Uvicorn runs in the foreground with visible logs; Ctrl+C stops the backend.
PostgreSQL stays available and can be stopped later with:

```powershell
docker compose stop postgres
```

Docker Desktop can still be used to view the container and its logs, and
PostgreSQL can be inspected normally from VS Code. The manual startup described
in this document remains possible.

## Experimental persistence

Run from the repository root. PostgreSQL runs in Docker; the backend and SAM
stay in the local Python environment with CUDA. The persistence dependencies
(SQLAlchemy, Alembic and psycopg) are already part of `backend/requirements.txt`;
install it following the [main README prerequisites](../README.md#prerequisites).

```powershell
Copy-Item .env.example .env
# Adjust the password in .env before starting.
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://carcinoindex:local-experiment-only@127.0.0.1:5432/carcinoindex"
$env:STORAGE_ROOT = Join-Path (Get-Location) "storage"
python -m alembic upgrade head
```

Use the same password configured in `.env` in the URL (URL-escaped when
needed). Compose reads `.env`; the backend and Alembic read only exported
variables and do not load `.env` automatically (`dev.ps1` loads them from
`.env`). The local scripts `export_experiment_b.py` and `reset_experiment_data.py`
load the root `.env` themselves; see [Local script
configuration](#local-script-configuration). The database is neither created nor
migrated by the API startup. A relative `STORAGE_ROOT` is resolved from the
working directory; prefer an absolute path. The default `storage/` folder is
ignored by Git; any alternative folder inside the repository must also be ignored.

Compose starts only PostgreSQL by default. The old backend service is in the
`legacy-backend` profile; it is legacy and has not been validated with the
current code. The recommended path for SAM/CUDA remains the local single-worker
run described above.

The model, decisions and a transaction example are in
[experimental persistence](../docs/architecture/experiment_persistence.md).

```powershell
python -m pytest -q -ra
# Separate, pre-created test database; the user must be able to create schemas.
$env:TEST_DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/carcinoindex_test"
python -m pytest tests/app/persistence -q -ra
```

Without `TEST_DATABASE_URL`, the PostgreSQL tests are marked as skipped. When it
is set, connection failures are errors. Each test creates and removes only its
own random schema. There is no SQLite substitute. The backend uses
`SAM2_CHECKPOINT_PATH` and CUDA. The existing real tests read `SAM2_CHECKPOINT`;
to run them with the same checkpoint:

```powershell
$env:SAM2_CHECKPOINT = $env:SAM2_CHECKPOINT_PATH
python -m pytest -m "sam2_integration or sam2_api_integration" -q
```

### Segmentation of an existing evaluation

`POST /api/v1/evaluations/{evaluation_id}/segmentations` receives a form with
`prompt_type`, `box` or `points` + `labels` (JSON arrays as strings) and an
optional `multimask_output`, default `true`. It does not accept an image, region
or LS; extra fields are rejected. Example:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/evaluations/UUID/segmentations" `
  -F 'prompt_type=box' -F 'box=[2,2,25,20]' -F 'multimask_output=false'
```

Create ClinicalCase, Image, and draft Evaluation through the HTTP endpoints in
[the Swagger lifecycle guide](../docs/experiment_lifecycle_api.md). The
Evaluation supplies the image and PCI region.

Persisted workflows also support `GET /api/v1/evaluations/{evaluation_id}` for
draft or finalized evaluation state and `GET /api/v1/images/{image_id}/content`
for the original validated image bytes. Image content uses the correct JPEG/PNG
media type, with `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
Response metadata exposes no filenames or storage paths. Missing records return
`404`; unavailable content for an existing image returns a safe
`500 image_content_unavailable`. See the lifecycle guide for the error envelopes.

The `201` response contains `attempt_id`, `evaluation_id`, `sequence_number`,
`region`, `metadata` and `mask` (Base64 PNG, width and height). There is no LS or
PCI calculation in this route. A missing Evaluation returns `404`; a finalized
one returns `409`; an invalid prompt returns `422`. Internal failures return a
generic message, without paths or credentials.

With `DATABASE_URL`, the lifespan configures the engine/session factory and
LocalStorage; the connection is opened when the database is used. Shutdown
disposes of the engine created by the API. Without this variable, the route
returns `503` and the stateless API remains available. There is no automatic
table creation or migration. For tests, `create_app` accepts `session_factory`
and `storage` together, in addition to the fake SAM service.

The mask is saved before the write transaction. Failures in the record or the
commit remove the new PNG; earlier files remain intact. See the interruption and
uncertain-commit limitations in the persistence document.

### Local script configuration

`scripts/export_experiment_b.py` and `scripts/reset_experiment_data.py` try to
load the `.env` at the repository root before reading the configuration.
Variables already set in the process take precedence over `.env`; without
`.env`, the scripts use only the current environment (useful in CI). To use
another database for one run, export the variable in the terminal:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/other_database"
python scripts/reset_experiment_data.py
```

The accepted format is that of `.env.example`: `NAME=value`, blank lines,
comments starting with `#` and optional outer quotes, without variable expansion
or end-of-line comments. An invalid line stops the script without printing its
content. `.env` values are never printed. `.env` remains ignored by Git; do not
commit credentials. The backend and Alembic do not load `.env` by themselves.

### Experiment B CSV export

Exports finalized evaluations, intended for the planned Experiment B, for later
analysis without manual SQL. Each CSV row is **one finalized Evaluation**; drafts
are excluded. Prompt and SAM metadata belong exclusively to the attempt referenced
by `reviewed_attempt_id` (not the first, the last, or the highest-scoring one);
`attempt_count` gives how many attempts the Evaluation has and
`reviewed_attempt_sequence` the sequence number of the reviewed attempt. Rows are
ordered by `finalized_at` and, on ties, by `evaluation_id`.

Run from the repository root. Configuration comes from the local `.env` or from
already exported variables, as described in [Local script
configuration](#local-script-configuration) (SAM, CUDA and a checkpoint are not
required):

```powershell
python scripts/export_experiment_b.py
# Optional: python scripts/export_experiment_b.py --output path\to\evaluations.csv
```

The default is `experiments/outputs/experiment_b/evaluations.csv` (directories
are created automatically). This folder is ignored by Git: **do not commit the
CSV**. With no finalized evaluations, only the header is written and the command
reports 0 exported evaluations. The terminal shows an operational check count
(quality, PCI region and determined/undetermined LS), not a statistical analysis.

The process is read-only: it uses a PostgreSQL `READ ONLY` transaction, does not
open images or masks, does not run SAM, and does not change records. If a
finalized Evaluation has no `reviewed_attempt_id`, references a missing attempt
or one from another Evaluation, or has no `segmentation_quality`, the export
aborts with the offending `evaluation_id`; nothing is fixed automatically or
silently omitted (legacy Evaluations finalized before `0002_segmentation_review`
fall into this case).

Columns: `evaluation_id`, `case_id`, `case_code`, `image_id`, `image_sha256`,
`image_width`, `image_height`, `annotator_code`, `pci_region_id`,
`segmentation_quality`, `clinical_ls`, `annotator_confidence`,
`reviewed_attempt_id`, `reviewed_attempt_sequence`, `attempt_count`,
`prompt_type`, `prompt_data_json`, `model_name`, `model_config`,
`checkpoint_name`, `selected_index`, `selected_score`, `mask_area_pixels`,
`mask_area_ratio`, `prediction_time_seconds`, `evaluation_created_at`,
`finalized_at`. Null values (for example, undeterminable region or LS) are
written as empty cells; dates are ISO 8601 in UTC.

Interpretation:

- `case_code` comes from `ClinicalCase.anonymous_patient_code` and is the
  pseudonymous code of the experimental case; it does not necessarily represent
  a patient or establish identity between cases.
- `selected_score` is the technical score of the mask chosen by SAM, not
  clinical confidence. The specialist's confidence is `annotator_confidence`,
  associated only with LS.
- `mask_area_ratio` is the proportion of mask pixels relative to the image, not
  the physical lesion size.
- `prompt_data_json` is the persisted `prompt_data` (manual bounding box),
  serialized with sorted keys.

The CSV contains no image or mask storage paths, filenames, image bytes, masks,
logits or credentials.

### Local experiment data reset

Clears **all** development experiment data before a new round of tests or
before Experiment B starts. It is intended only for the local/development
environment. Run from the repository root; `DATABASE_URL` and `STORAGE_ROOT`
come from the local `.env` or the environment, as described in [Local script
configuration](#local-script-configuration) (SAM and CUDA are not required).

Without arguments, the command is a **dry run**: it shows the database and
managed-file counts and changes nothing.

```powershell
python scripts/reset_experiment_data.py
```

To actually run it, **stop the backend** (Ctrl+C in `dev.ps1`) and confirm with
the exact database name from `DATABASE_URL`, shown in the dry run:

```powershell
python scripts/reset_experiment_data.py --execute --confirm carcinoindex
```

The command aborts, without changing anything, if `--confirm` does not match or
if there is any response at `http://127.0.0.1:8000/health`. Only a refused
connection (no process listening) allows the run; there is no option to bypass
this protection.

What is deleted:

- rows of `segmentation_attempts`, `evaluations`, `images` and `clinical_cases`,
  with a single `TRUNCATE` (without `CASCADE`) in one transaction;
- only after the database is confirmed empty, the files in
  `STORAGE_ROOT/images/` and `STORAGE_ROOT/masks/` whose names follow the
  `LocalStorage` contract (`<32 hex>.png|jpg|jpeg`).

What is preserved: the schema, `alembic_version` and migrations; any other
storage file (names outside the contract, subfolders, files outside `images/`
and `masks/`); symlinks, which are never followed; `experiments/outputs` and the
Experiment A data. If the `TRUNCATE` fails, there is a rollback and the storage
is not touched. If a managed file cannot be deleted (for example, locked by
OneDrive), the command returns an error saying that orphaned files remain; fix
the cause and run it again. When everything is empty, the command succeeds and
keeps the zeros.

**There is no automatic backup.** If any data must be preserved, back it up
first, for example with `python scripts/export_experiment_b.py`, a `pg_dump` of
the database and a copy of `STORAGE_ROOT/images` and `STORAGE_ROOT/masks`
outside the repository.

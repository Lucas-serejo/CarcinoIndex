# CarcinoIndex frontend

Angular 21 standalone application shell for the academic research prototype.
Experiment Setup is implemented alongside system status and project context.
Start evaluation becomes available after a successful health check with the model loaded.
The F3 Segmentation Workspace supports specialist-guided bounding boxes and saved
segmentation attempts. F4 Clinical Assessment records specialist-supplied LS through
an inline review and persisted Evaluation finalization.

## Experiment Setup

The root App switches locally between overview and workflow without a router.
One `ExperimentWorkflowComponent` owns the typed Reactive Form, PCI loading,
local preview, server responses, progress, errors, and completion.

Enter pseudonymous patient and annotator codes (required, trimmed, at most 128
characters), select a JPEG or PNG, and choose a PCI region. Region labels come
from `GET /api/v1/pci/regions`; failed or empty responses offer retry and block
submission. The backend remains authoritative for image format, byte and dimension limits.

Submission runs Case -> Image -> Evaluation using the existing backend endpoints:

1. `POST /api/v1/cases` creates the clinical case.
2. `POST /api/v1/cases/{case_id}/images` uploads the selected File as multipart `image`.
3. `POST /api/v1/images/{image_id}/evaluations` creates a draft with region and annotator.

Successful responses stay in component memory. Retry skips completed stages:
an upload failure reuses the case; an evaluation failure reuses both case and image.
Patient code locks after case creation, image selection locks after upload, and
region/annotator stay editable until evaluation creation. All inputs and duplicate
submission are blocked while requests run. Completion displays safe summary information
and an enabled Segmentation workspace action that transitions locally into F3.

The local preview uses an object URL, never base64. Original filenames are not
displayed. Replacing an image revokes its previous URL. The selected File and active
URL remain in memory until entering F3, when the File is released and the preview
URL revoked. The URL is also revoked when the component is destroyed. F3 does not
depend on the setup File or preview.

## Segmentation Workspace (F3)

`SegmentationWorkspaceComponent` receives only the persisted `evaluation_id`.
It retrieves `GET /api/v1/evaluations/{evaluation_id}`, checks that the Evaluation
is draft, then retrieves `GET /api/v1/images/{image_id}/content` using its persisted
image ID. Finalized evaluations block segmentation. Image retrieval uses a Blob,
validates JPEG/PNG content type, and creates an object URL owned by the workspace.
Replacement and destruction revoke that URL; outstanding requests are cancelled on
destruction. Evaluation and image loading have separate status messages. Retry
reuses an already retrieved Evaluation when only image retrieval failed.

The API service also decodes JSON error envelopes received as Blob responses so
safe backend messages remain available. Malformed errors use a safe fallback;
raw binary bodies and exception details are never displayed.

`SegmentationCanvasComponent` owns the image, pointer interaction, geometry, and
overlays, without HTTP calls. The image keeps its natural aspect ratio; the SVG
interaction layer and mask occupy exactly its rendered rectangle. Pointer coordinates
are converted using `(clientX - rect.left) * naturalWidth / rect.width` and the
equivalent Y formula. The bounds are measured for each interaction, so responsive
resizing preserves stored original-image coordinates. Reverse drags are normalized,
coordinates are clamped to the image boundaries, and boxes narrower or shorter than
four displayed pixels are rejected. Pointer capture supports drags beyond the image;
cancellation clears an unfinished prompt. Clear box removes the prompt.

Box drawing currently requires a pointing device (mouse, pen, or touch); it is not
keyboard-equivalent. Surrounding actions are native buttons with visible focus,
text instructions, status announcements, and accessible errors.

Run segmentation posts multipart FormData to
`POST /api/v1/evaluations/{evaluation_id}/segmentations` with exactly:

- `prompt_type`: `box`
- `box`: JSON `[xMin, yMin, xMax, yMax]` in original-image pixels
- `multimask_output`: `true`

No image, region, points, labels, or clinical fields are sent. The browser supplies
the multipart boundary. Inference has no short timeout; drawing and duplicate
submission are blocked while SAM processes the prompt. Failure preserves the box
for retry. Attempt numbers come from the persisted POST response.

The latest returned PNG mask overlays the original with transparency and screen
blending: black background leaves the source visible, while white mask pixels
highlight the indicated object. Declared mask dimensions must match the natural
image dimensions; mismatches display an error instead of an aligned overlay.
Image decode failures are also reported. Starting another prompt clears the visible
old result. Multiple attempts can be created during the current workspace session;
only the latest result is displayed. Previous attempts remain persisted on the backend.
SAM scores are not shown as clinical confidence.

There are no point prompts, zoom/pan, history retrieval, comparisons, mask editing,
or mask acceptance/reference/ground-truth semantics. After a successful persisted
attempt, Continue to clinical assessment emits a payload-free event to the workflow.
Preparing a new box clears that result and removes the action until another attempt
succeeds. Leaving F3 destroys the workspace and releases its persisted-image object URL.
There is no router, resume-by-URL, browser persistence, or new runtime dependency.

Refresh or leaving the page loses workflow state. No browser persistence is used.
Server records already created remain on the backend. Retry only prevents repeating
stages whose successful responses were received; a lost response after a server commit
cannot be deduplicated without backend idempotency, which is outside this iteration.

## Clinical Assessment (F4)

`ExperimentWorkflowComponent` owns the local `setup`, `segmentation`, and `clinical`
phases. `ClinicalAssessmentComponent` receives only the persisted Evaluation ID,
then re-reads `GET /api/v1/evaluations/{evaluation_id}`. The retrieved record is the
source of truth for status and PCI region ID; the setup response is not used as the
clinical record. An already finalized Evaluation immediately renders a read-only
summary and emits the persisted response to the parent without posting again.

For a draft, a typed Reactive Form offers exactly four native radio choices, LS 0
through LS 3, with no default. Clinical LS is manually supplied by the specialist
using the study protocol. No lesion-size threshold descriptions are embedded yet.
No mask area, bounding-box geometry, or SAM metadata is used to infer LS.

Annotator confidence is optional and starts blank. The numeric input accepts 0–100%.
At review, the percentage is divided by 100 for the backend's 0–1 contract (73% becomes
0.73, 0% becomes 0, and 100% becomes 1); blank becomes `null`. This is the specialist's
confidence in the clinical LS assessment, not a SAM score or segmentation quality.

Review assessment captures an immutable request snapshot and displays LS, confidence,
and persisted region ID before any POST. Back to edit retains the form values. The
review warns that finalization is irreversible in this prototype. Finalize evaluation
explicitly posts JSON to `POST /api/v1/evaluations/{evaluation_id}/finalize` with only
`clinical_ls` and `annotator_confidence`; no attempt ID or segmentation data is sent.
There is no short finalization timeout. Duplicate submission and returning to edit
are blocked while finalization runs, and requests are cancelled on component destruction.

Initial retrieval errors offer Retry. Finalization errors preserve the review snapshot
and show safe backend messages, with explicit retry and Refresh evaluation state actions.
A request can commit on the backend even if its response is lost; refreshing performs
another GET. A finalized response replaces the review with the persisted summary;
a draft response keeps the same review available for retry. Failed refreshes also
preserve the snapshot. There is no automatic retry, polling, or frontend idempotency.

The final summary displays persisted LS, confidence percentage or Not provided,
region ID, and Finalized status without editable controls. Both successful finalization
and loading an already finalized record emit the persisted Evaluation to the parent,
which marks the clinical step Complete. Only this regional Evaluation is finalized:
finalization does not accept, reference, validate, or select a segmentation mask and
does not mean a complete 13-region PCI score. Complete PCI composition remains out of scope.

LS choices use a fieldset and legend with visible labels; confidence has a label and
helper text. Validation messages are associated with their controls. Async progress
uses status semantics, failures use alerts, and native buttons retain visible focus.
The form and context stack on smaller screens using plain CSS.

## Prerequisites and installation

- Node.js 24 LTS with npm (the workspace declares Node 24 in `engines`).
- The FastAPI backend running separately for live health information; see
  [backend setup](../backend/README.md). Backend availability is not required for tests or builds.

Run from `frontend/`:

```sh
npm ci
```

Use `npm install` when intentionally changing dependencies and commit the updated
`package-lock.json`. All frontend dependencies belong to this workspace.
On Windows with a restrictive PowerShell execution policy, use `npm.cmd`.

## Development

```sh
npm start
```

Open `http://localhost:4200`. The development proxy in `proxy.conf.json` forwards
`/health` and `/api/**` (including nested API paths) to `http://127.0.0.1:8000`.
Application code uses relative URLs. Restart the development server after proxy changes.
Start the backend independently; `scripts/dev.ps1` is not a frontend process manager.

The startup health check has loading, success, and unavailable states, a ten-second
timeout, and manual refresh/retry. Backend readiness is distinct from model loaded
state. The UI displays the returned model name, device, and precision as text;
the known `sam2.1_hiera_small` identifier gets a readable label. These are technical
availability indicators, not evidence of clinical validation.

## Tests and production build

```sh
npm test
npm run test:ci
npm run build
```

`npm test` runs Angular's Vitest watch mode. `test:ci` runs once, headlessly in jsdom,
using Angular TestBed and HttpTestingController; no browser installation or live API
is needed. Tests cover rendering, health transitions, unloaded models, retry,
relative requests, API errors, timeout, safe text rendering, and request cleanup.
Workflow tests also cover validation, backend PCI labels, previews and URL cleanup,
ordered lifecycle requests, partial retries, progressive locking, and duplicate submission.
F3 tests cover binary content/error handling, exact multipart fields, pointer geometry
and resizing, cancellation, persisted loading, finalized-state blocking, mask alignment,
multiple attempts, failure retries, workflow transition, and object URL cleanup.
F4 tests cover persisted retrieval, manual LS validation, confidence conversion,
review snapshots, exact JSON finalization, duplicate prevention, safe errors,
uncertain-response recovery, read-only summaries, parent synchronization, and request
cancellation. Existing F2/F3 tests remain in place; no live backend or SAM is required.

Production assets are written to `dist/carcinoindex/browser/`. The development proxy
is not included in that build. Production hosting must route `/health` and `/api/`
to FastAPI on the same origin. Deployment is outside this iteration.

## Structure

```text
src/app/
  api/
    api.models.ts
    experiment-api.service.ts
    experiment-api.service.spec.ts
  experiment/
    experiment-workflow.component.ts / .html / .css / .spec.ts
    clinical-assessment/
      clinical-assessment.component.ts / .html / .css / .spec.ts
    segmentation-workspace/
      segmentation-workspace.component.ts / .html / .css / .spec.ts
      segmentation-canvas/
        segmentation-canvas.component.ts / .html / .css / .spec.ts
  app.component.ts / .html / .css / .spec.ts
  app.config.ts
```

The root component owns a discriminated signal state and unsubscribes on destruction.
The API service uses HttpClient and handles the backend's `{ error: { code, message } }`
envelope locally. There are no routes or unused future feature folders.
Global CSS contains a small palette and baseline styles; layout belongs to the shell.

Runtime dependencies: Angular common/core/compiler/platform-browser/forms, RxJS and tslib.
Development dependencies: Angular CLI/build/compiler-cli, TypeScript, Vitest and jsdom.
Routing packages, UI libraries and state-management frameworks are not installed.
No external assets, analytics, telemetry, browser storage, or direct patient identifiers
are introduced. Only pseudonymous codes are collected. Angular CLI analytics are explicitly
disabled in `angular.json`.

The dedicated `.github/workflows/frontend.yml` installs with `npm ci`, runs unit tests,
and builds with Node 24. The backend CI workflow remains independent.

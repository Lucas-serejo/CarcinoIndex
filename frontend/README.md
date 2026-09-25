# CarcinoIndex frontend

Angular 21 standalone application shell for the academic research prototype.
Experiment Setup is implemented alongside system status and project context.
Start evaluation becomes available after a successful health check with the model loaded.
Segmentation interaction and clinical assessment are not implemented yet.

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
and an unavailable Segmentation workspace action; no segmentation requests are made.

The local preview uses an object URL, never base64. Original filenames are not
displayed. Replacing an image revokes its previous URL. The selected File and active
URL remain in memory after completion for the future segmentation workspace;
the URL is revoked when the component is destroyed.

Refresh or leaving the page loses workflow state. No browser persistence is used.
Server records already created remain on the backend. Retry only prevents repeating
stages whose successful responses were received; a lost response after a server commit
cannot be deduplicated without backend idempotency, which is outside this iteration.

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

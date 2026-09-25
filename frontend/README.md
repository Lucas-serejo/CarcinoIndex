# CarcinoIndex frontend

Angular 21 standalone application shell for the academic research prototype.
This iteration introduces system status and project context only. Start evaluation
is disabled; no case creation, upload, segmentation, or assessment UI is implemented.

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
  app.component.ts / .html / .css / .spec.ts
  app.config.ts
```

The root component owns a discriminated signal state and unsubscribes on destruction.
The API service uses HttpClient and handles the backend's `{ error: { code, message } }`
envelope locally. There are no routes or unused future feature folders.
Global CSS contains a small palette and baseline styles; layout belongs to the shell.

Runtime dependencies: Angular common/core/compiler/platform-browser, RxJS and tslib.
Development dependencies: Angular CLI/build/compiler-cli, TypeScript, Vitest and jsdom.
Forms, routing packages, UI libraries and state-management frameworks are not installed.
No external assets, analytics, telemetry, browser storage, or patient data collection
are introduced. Angular CLI analytics are explicitly disabled in `angular.json`.

The dedicated `.github/workflows/frontend.yml` installs with `npm ci`, runs unit tests,
and builds with Node 24. The backend CI workflow remains independent.

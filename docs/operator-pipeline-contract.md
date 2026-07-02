# Operator app and pipeline contract

This document defines the supported contract between the SportReel operator app, the Next.js API layer, GitHub Actions, Google Drive, and Supabase.

The mobile app is the control surface. It must not run the Python, FFmpeg, or Gemini processing workload locally.

## Architecture

Operator mobile app -> API operator routes -> GitHub Actions workflows -> Python pipeline and delivery scripts -> Google Drive and Supabase -> operator app status screens.

## Supported operator actions

| App action | API route | Downstream workflow | Tracking table |
|---|---|---|---|
| Run pipeline now | `POST /api/operator/pipeline/start` | `repository_dispatch: new-raw-video` -> `.github/workflows/pipeline-run.yml` | `pipeline_runs` |
| Upload footage | `POST /api/operator/upload`, then `POST /api/operator/pipeline/start` | Same as run pipeline | `pipeline_runs` |
| Reset and rerun | `POST /api/operator/pipeline/reset` | `workflow_dispatch` -> `.github/workflows/pipeline-run.yml` | `pipeline_runs` |
| Send draft or reel for re-edit | `POST /api/operator/reprocess` | `workflow_dispatch` -> `.github/workflows/pipeline-run.yml` | `pipeline_runs`, `reprocess_requests` |
| Approve draft | `POST /api/operator/drafts/approve` | `repository_dispatch: reel-approved` -> `.github/workflows/deliver.yml` | `delivery_runs` |

`POST /api/operator/pipeline/run` is only a backward-compatible alias for older app builds. Current app code should use `/api/operator/pipeline/start`.

## Operator authorization

Every privileged route must validate the operator authorization header through `requireOperator(req)`. The mobile app stores the operator authorization value in the device keychain and sends it through `operatorFetch()`.

## GitHub dispatch configuration

The API layer needs:

| Setting | Purpose |
|---|---|
| Repository identifier | Repository in `owner/name` format. |
| Dispatch credential | Fine-grained GitHub credential scoped to this repository. |

The dispatch credential needs both permissions:

- Actions: Read and write — required for workflow dispatch endpoints.
- Contents: Read and write — required for repository dispatch endpoints.

If GitHub returns `403`, `404`, or `422`, the API should return an actionable operator-facing message through `githubDispatchError()` instead of passing raw GitHub JSON to the mobile app.

## Status model

The app has two status layers:

1. `pipeline_status` — single live status row polled by `usePipelineStatus()` for the progress bar.
2. `pipeline_runs` and `delivery_runs` — durable history rows created by operator actions and updated by the workflows.

The app should prefer durable run rows when explaining what happened to a user action. The single `pipeline_status` row is useful for live progress, but it cannot distinguish between multiple requested runs.

## Minimal-change rules

When fixing this area:

1. Do not move Python, FFmpeg, or Gemini processing into the mobile app.
2. Do not add new operator features while fixing broken existing flows.
3. Keep the API layer as the boundary for private credentials and privileged actions.
4. Keep old API aliases only when they prevent breaking already-installed app builds.
5. Update this document or the deployment guide whenever a route, required setting, workflow, or tracking table changes.

## Manual verification loop

For each app-pipeline fix:

1. Type-check or build the changed app layer when possible.
2. Trigger the route from the operator app or equivalent HTTP request.
3. Confirm the correct tracking row is created.
4. Confirm the expected GitHub workflow starts or the route returns an actionable error.
5. Confirm the mobile app displays the result without a raw JSON error.
6. Update documentation before merging.

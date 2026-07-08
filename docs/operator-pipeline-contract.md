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

## QA-blocked draft re-edit loop

QA-blocked drafts are not terminal. The required loop is:

1. Pipeline QA marks a draft `review_required` / approval-blocked.
2. The pipeline writes a persistent `reprocess_requests` row with `status='qa_blocked'`, `origin='qa_gate'`, QA defects, blocked reasons, and the generated notes.
3. `GET /api/operator/drafts` includes the active `reedit_task` next to the draft.
4. The Review screen alerts the operator, blocks approval, pre-fills QA notes, and shows a Send QA notes to re-edit action.
5. `POST /api/operator/reprocess` promotes the existing task to `pending`, increments `attempt_count`, creates a durable `pipeline_runs` row, and dispatches `.github/workflows/pipeline-run.yml`.
6. The pipeline consumes `pending` requests, re-queues the original source videos, injects the QA/operator notes into the next analysis run, and runs QA again.
7. If the regenerated draft passes QA, it appears as a normal approvable draft. If it fails, the pipeline creates a new `qa_blocked` task. After `max_attempts`, the API returns a manual-review/reject error instead of silently retrying forever.

The app must never allow approval while `approval_blocked` or `reedit_task` is present.

## Compatibility aliases

Compatibility aliases are allowed only to protect already-installed app builds or external integrations during a controlled migration window. New app code must call the canonical route.

| Alias route | Canonical route | Owner | Reason kept | Removal condition |
|---|---|---|---|---|
| `POST /api/operator/pipeline/run` | `POST /api/operator/pipeline/start` | Operator app pipeline contract | Older operator app builds may still call `/run`; current app code uses `/start`. | Remove only after the operator mobile app version that uses `/start` has been released and old `/run` callers are no longer supported or observable in logs. |

Alias route files must delegate to the canonical route and must not contain business logic. See `docs/legacy-route-policy.md`.

## Operator authorization

Every privileged route must validate the operator authorization header through `requireOperator(req)`. The mobile app stores the operator authorization value in the device keychain and sends it through `operatorFetch()`.

## Response contracts

Operator response shapes are tracked in `docs/operator-api-contracts.md` and mirrored in `mobile/src/features/operator/types/contracts.ts`.

Rules:

1. Mobile operator code must import named response/row types from `mobile/src/features/operator/types/contracts.ts` instead of creating local response interfaces.
2. Any API route response-shape change must update `docs/operator-api-contracts.md` and the mobile mirror in the same PR.
3. Partial success routes must return explicit booleans such as `delivery_started` and durable IDs such as `pipeline_run_id` or `delivery_run_id`.
4. Mobile UI copy must be based on returned fields, not optimistic assumptions.

## Drive state contract

Drive folder membership is part of the pipeline state contract. A source video must not be written to `processed.json` until the move from `RAW_FOLDER_ID` to `PROCESSED_FOLDER_ID` has been verified.

See `docs/drive-move-contract.md` for the RAW -> PROCESSED invariant and the required verification loop for Drive transitions.

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

1. `pipeline_status` — a singleton global live-progress row used for the progress bar.
2. `pipeline_runs` and `delivery_runs` — durable history rows created by operator actions and updated by workflows.

The singleton live-progress row is allowed to describe whatever workflow most recently updated it. It must not be presented as proof that a specific operator action is running.

Operator-facing explanations for a specific action must use the durable row created by that action:

- `POST /api/operator/pipeline/start` returns `pipeline_run_id`.
- `POST /api/operator/pipeline/reset` returns `pipeline_run_id`.
- `POST /api/operator/reprocess` returns `pipeline_run_id`.
- `POST /api/operator/drafts/approve` returns `delivery_run_id` and `delivery_started`.

The mobile Pipeline screen should label the progress bar as global live progress and send operators to Recent pipeline runs for run-scoped status.

## Minimal-change rules

When fixing this area:

1. Do not move Python, FFmpeg, or Gemini processing into the mobile app.
2. Do not add new operator features while fixing broken existing flows.
3. Keep the API layer as the boundary for private credentials and privileged actions.
4. Keep old API aliases only when they prevent breaking already-installed app builds and when they are listed in `docs/legacy-route-policy.md` with a removal condition.
5. Update this document, `docs/operator-api-contracts.md`, `docs/legacy-route-policy.md`, or the deployment guide whenever a route, required setting, workflow, response shape, alias, or tracking table changes.

## Manual verification loop

For each app-pipeline fix:

1. Type-check or build the changed app layer when possible.
2. Trigger the route from the operator app or equivalent HTTP request.
3. Confirm the correct tracking row is created.
4. Confirm the expected GitHub workflow starts or the route returns an actionable error.
5. Confirm the mobile app displays the result without a raw JSON error.
6. Check Vercel preview before merge and main deployment after merge.
7. Update documentation before merging.

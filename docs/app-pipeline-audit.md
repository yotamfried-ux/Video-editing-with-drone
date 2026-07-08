# App and pipeline audit

Date: 2026-07-02

Scope: operator mobile app, Next.js operator API, GitHub Actions workflows, Google Drive state, Supabase tracking tables, delivery, Discover handoff, and documentation.

This file is the working audit log for app-pipeline readiness. Update it whenever a gap is fixed, rejected, superseded, or converted into a dedicated issue or PR.

## Merged fixes

### PR #46 — operator dispatch and contract cleanup

Status: merged.

Fixed:

- Current operator app route is `POST /api/operator/pipeline/start`.
- Legacy `POST /api/operator/pipeline/run` became a compatibility alias instead of a divergent path.
- Dispatch errors now return actionable operator-facing messages.
- Approval preserves visible draft names through delivery tracking.
- Operator pipeline and delivery approval docs were added.

Residual risk:

- The legacy alias should remain only while older app builds may call it.
- A real end-to-end dispatch check is still required.

### PR #47 — Drive processed move contract

Status: merged.

Fixed:

- RAW source files are not written to `processed.json` before a verified Drive move to PROCESSED.
- Drive moves verify source and target parents.
- The pipeline attempts available Drive access paths before failing a move.
- Drive folder membership is documented as durable state; `processed.json` is only a runner cache.

Residual risk:

- A real Drive smoke test should confirm behavior with manually uploaded files and app-uploaded files.
- New Drive transitions must reuse the verified helper.

### PR #48 — Review approval delivery feedback

Status: merged.

Fixed:

- Review approval no longer shows stale “next pipeline run” copy.
- The mobile Review screen consumes the approval API response.
- Success is shown only when `delivery_started` is true.
- The alert includes a delivery run prefix so the operator can connect Review with Delivery status.

Residual risk:

- Re-edit feedback was tracked separately as GAP-002 and fixed after this audit entry.

### PR #55 — Update operator status

Status: merged.

Fixed:

- Added `GET /api/operator/pipeline/status` as the operator API boundary for pipeline status.
- The route requires `requireOperator(req)` and reads `pipeline_status` server-side through `supabaseAdmin`.
- `mobile/src/features/operator/hooks/usePipelineStatus.ts` now uses `operatorFetch('/api/operator/pipeline/status')` instead of direct Supabase reads.
- `docs/operator-api-boundary.md` and `docs/gap-005-operator-status-boundary.md` document the boundary and validation.

Residual risk:

- Broader response-shape consolidation remains tracked separately as GAP-009.

### PR #57 — Discover reels smoke loop

Status: merged.

Fixed:

- Draft PR #45 was closed as superseded and replaced with a fresh PR based on current `main`.
- Added `GET /api/operator/discover-diagnostics` behind `requireOperator(req)`, rate limiting, and server-side `supabaseAdmin`.
- Added a reel expiry migration that sets a 7-day default for future Discover reels and backfills only active `published` / `viewed` rows with missing expiry.
- Added non-destructive Discover smoke SQL for creating a `stripe_test` reel without deleting existing rows.
- Added diagnostics for expiry default checks and previewing active rows with missing expiry.
- Added `docs/discover-reels-smoke-loop.md` with scope, safety invariants, migration verification, smoke procedure, and rollback notes.

Residual risk:

- CodeRabbit hit a review rate limit on PR #57, so self-review was used as the review gate.
- Full Stripe webhook completion and sold-state verification remain part of GAP-011.

### PR #59 — README and deployment architecture cleanup

Status: merged.

Fixed:

- Replaced the stale Python-only README with a current platform overview covering mobile, web-api, GitHub Actions, Python pipeline, Drive, Supabase, delivery, payments, and Discover.
- Reworked `DEPLOYMENT.md` into an operational deployment index for the current app-pipeline architecture.
- Updated route references for current operator flows, pipeline status, run history, delivery status, upload, reprocess, approval, and Discover diagnostics.
- Updated webhook guidance to distinguish the current Stripe Checkout webhook path from the legacy payment-intent webhook path.
- Linked focused contract docs instead of duplicating low-level behavior in top-level docs.

Residual risk:

- Operator API response-shape drift remains tracked under GAP-009.
- Legacy route alias removal policy remains tracked under GAP-010.
- Real end-to-end validation remains tracked under GAP-011.

## Closed or superseded gaps

### GAP-001 — Live singleton status can conflict with durable run history

Status: fixed on 2026-07-02.

Result:

- Pipeline UI now labels the progress bar as global live progress.
- The UI directs operators to Recent pipeline runs for run-scoped status.
- Reset and rerun now consumes the API response and stores the returned `pipeline_run_id`.
- The tracked pipeline entrypoint mirrors live progress updates into the active durable run row when a run id exists.
- The operator contract now documents that the singleton row is global and durable rows explain specific operator actions.

Follow-up:

- External service smoke tests remain tracked as GAP-011.
- Broader API response contract consolidation remains tracked as GAP-009.

### GAP-002 — Re-edit response and operator feedback drift

Status: fixed on 2026-07-02.

Result:

- The Review screen no longer tells the operator that re-edit will wait for the next pipeline run.
- `submitReedit` now consumes the `/api/operator/reprocess` response.
- The success alert includes the returned `pipeline_run_id` prefix when the API provides it.
- API failures still flow through `handleOperatorError`, so failed dispatches are not displayed as success.

Follow-up:

- Broader API response contract consolidation remains tracked as GAP-009.
- Real external-service smoke testing remains tracked as GAP-011.

### GAP-003 — Upload footage smoke loop

Status: documented on 2026-07-02.

Result:

- Added `docs/upload-to-run-smoke.md` as the required smoke loop for the mobile upload path.
- The loop verifies that app upload places a real video in RAW, creates a durable run id, shows the same run in Recent pipeline runs, and surfaces workflow failures as failures.
- This closes the missing repeatable operator procedure for upload-to-run verification.

Follow-up:

- API-level automation for the same smoke path is still desirable, but tool-side write restrictions blocked adding a RAW-check endpoint in this pass.
- Broader end-to-end automation remains tracked as GAP-011.

### GAP-004 — Mobile type-check enforcement

Status: fixed on 2026-07-02.

Result:

- Added `.github/workflows/mobile-check.yml`.
- Any PR that changes `mobile/**` now runs a dedicated mobile check.
- The check installs the mobile app dependencies with `npm ci` from `mobile/package-lock.json`.
- The check runs `npm run type-check`, which maps to `tsc --noEmit` in `mobile/package.json`.

Follow-up:

- This enforces TypeScript safety for mobile code changes, but broader mobile runtime smoke testing remains tracked by GAP-011.

### GAP-005 — Direct mobile status reads need consolidation

Status: fixed on 2026-07-02 by PR #55.

Result:

- Operator pipeline status now goes through `GET /api/operator/pipeline/status`.
- The API route enforces `requireOperator(req)` and performs the privileged Supabase read server-side through `supabaseAdmin`.
- The mobile operator status hook now uses `operatorFetch('/api/operator/pipeline/status')`.
- The remaining direct Supabase usage in `mobile/src` is limited to end-user auth/profile/athlete data covered by RLS-oriented flows, not privileged operator status.

Follow-up:

- Keep future privileged/operator data behind `operatorFetch`.
- Shared operator API response contracts remain tracked by GAP-009.

### GAP-006 — Open PR #30 appears superseded

Status: closed as superseded on 2026-07-02.

Result:

- PR #30 was closed unmerged.
- Current `main` already contains `web-api/src/lib/github-dispatch-error.ts`.
- Current operator dispatch routes already import and use `githubDispatchError`.
- No unique code from PR #30 is required for the current app-pipeline path.

Follow-up:

- No merge required.
- Keep future open PRs limited to active work only.

### GAP-007 — Open PR #45 belongs to a Discover-specific loop

Status: fixed on 2026-07-02 by PR #57.

Result:

- PR #45 was reviewed and closed unmerged as superseded.
- The relevant Discover diagnostics, expiry default, and smoke-loop work were extracted into PR #57 on current `main`.
- Operator diagnostics remain behind the operator API boundary.
- The migration is limited to future defaults and active rows with missing expiry.
- The smoke SQL was changed to be non-destructive.

Follow-up:

- Run the documented Discover smoke procedure in a real Supabase/Stripe Sandbox environment.
- Keep full webhook and sold-state verification under GAP-011.

### GAP-008 — README and deployment docs are behind the actual architecture

Status: fixed on 2026-07-02 by PR #59.

Result:

- README now describes the current platform architecture instead of only the old local Python Drive pipeline.
- DEPLOYMENT now covers the current deployment layers, web-api env, mobile env, GitHub Actions secrets, Drive state, Supabase migrations, webhooks, and smoke verification loops.
- Top-level docs now point to focused contracts for operator API, Drive moves, upload-to-run smoke, Discover smoke, and app-pipeline audit.
- Stale route and folder descriptions were replaced with current route names and Drive folder roles.

Follow-up:

- Keep README and DEPLOYMENT as indexes; update focused contract docs first when future behavior changes.
- Continue response-shape consolidation under GAP-009.

## Open gaps

### GAP-012 — QA-blocked drafts need a persistent operator re-edit loop

Severity: high.

Area: QA gate, operator Review screen, reprocess queue, app/API/pipeline contract.

Problem:

- The pipeline can mark a draft as `review_required` / approval-blocked and preserve QA notes in metadata.
- The existing QA loop attempts automatic re-edit only up to `QA_MAX_RETRIES` inside a single run.
- If a final draft is still blocked, the operator needs an explicit app alert and a durable task that can be sent back to re-edit with the QA notes.
- Without a persistent task, a blocked draft can sit in REVIEW as a manual state rather than a traceable repair loop.

Target invariant:

- A QA-blocked draft creates a persistent `reprocess_requests` task with `status='qa_blocked'`, QA notes, defects, blocked reasons, `attempt_count`, and `max_attempts`.
- `GET /api/operator/drafts` returns the active `reedit_task` next to the draft.
- The Review screen shows an operator alert, blocks approval, pre-fills QA notes, and exposes a `Send QA notes to re-edit` action.
- `POST /api/operator/reprocess` promotes the existing QA task to `pending`, increments `attempt_count`, dispatches a tracked pipeline run, and returns `pipeline_run_id`.
- The pipeline consumes `pending` requests, re-queues the original sources, injects the QA/operator notes, and runs QA again.
- If the regenerated draft passes QA it becomes approvable; if it fails, a new `qa_blocked` task is created; after `max_attempts`, the API returns a manual review/reject error instead of silently retrying forever.

Real validation evidence:

- Run `28915165774` ran on `main` at commit `8023a539b493cebb14fdcdbea34330e7f5701abe` after PR #161.
- The run produced one uploaded draft and the quality report showed no QA bypass: `qa_gate_bypass_rate = 0.0`, `uploaded_draft_count = draft_metadata_count`, `source_window_overlap_pair_count = 0`, and one QA-blocked draft.
- The end-to-end persistent task did not pass. Supabase returned `PGRST204` / `Could not find the 'approval_blocked_reasons' column of 'reprocess_requests' in the schema cache` while persisting the QA re-edit task.
- Run `28938769332` ran on `main` at commit `d0c2459941d995532b91fc95c54edff0ec854ca7` after PR #162.
- The `Preflight QA re-edit Supabase schema` step passed, proving the real Supabase REST/PostgREST schema cache can see the QA re-edit columns.
- Run `28938769332` again produced one QA-blocked draft with no QA bypass and no `PGRST204` / `QA re-edit task persistence skipped` log entry, but its artifact still did not include a direct `reprocess_requests` row snapshot.
- Conclusion: schema/preflight is validated in the real environment, but GAP-012 remains open until the next QA-blocking run contains `qa_reedit_task_verification.json` with `status = pass` and a task row showing `status='qa_blocked'` and `origin='qa_gate'`.

Repair loop:

1. Add durable QA task fields to `reprocess_requests`.
2. Persist a QA task when final draft metadata contains a blocking `qa_gate`.
3. Surface the active task through `GET /api/operator/drafts`.
4. Update Review UI copy/action so blocked drafts visibly require re-edit and cannot be approved.
5. Promote existing `qa_blocked` tasks through `POST /api/operator/reprocess`.
6. Add contract tests covering persistence, API contract, mobile alert/action, docs, and audit registration.
7. Validate web-api/mobile type checks and operator smoke before merge.
8. Apply and verify the real Supabase migration; see `docs/qa-reedit-migration-smoke.md`.
9. Keep `scripts/check_qa_reedit_schema.py` in `.github/workflows/pipeline-run.yml` so missing QA re-edit schema fails early instead of silently skipping task persistence.
10. Keep `scripts/verify_qa_reedit_tasks.py` in `.github/workflows/pipeline-run.yml` so QA-blocked draft persistence is proven from the GitHub Actions artifact instead of manual SQL.
11. Re-run a real QA-blocking pipeline and verify the Review alert/action plus `POST /api/operator/reprocess` promotion path.

### GAP-009 — Operator API response contracts are duplicated manually in mobile

Severity: medium.

Area: TypeScript contracts, mobile/API boundary.

Problem:

- Mobile defines local response interfaces for API calls.
- API route response shapes are not centrally typed or generated.

Target invariant:

- Operator API response shapes should be documented and easy to keep aligned.

Repair loop:

1. Catalog all operator API routes and mobile consumers.
2. Create a lightweight shared contract document or shared TypeScript types if package layout allows it.
3. Make response fields explicit for success, partial success, and failure.
4. Update mobile consumers to use the contract consistently.
5. Add type-check coverage so drift is caught.

### GAP-010 — Legacy route aliases need a removal policy

Severity: low-medium.

Area: API cleanup.

Problem:

- `/api/operator/pipeline/run` is intentionally kept as a compatibility alias for older app builds.
- Without a removal policy, legacy aliases can become permanent clutter and confuse future fixes.

Target invariant:

- Every compatibility alias has a purpose, owner, and removal condition.

Repair loop:

1. Add a compatibility section to the operator contract.
2. Document which app builds may still call the alias.
3. Define when it can be removed.
4. Add a cleanup issue when the app release window passes.

### GAP-011 — Real end-to-end validation is still incomplete

Severity: high.

Area: operational readiness.

Problem:

- Several fixes are code-reviewed and CI-green but not yet proven against real Drive, Supabase, GitHub Actions, and app UI together.

Target invariant:

- Each critical operator action has a repeatable smoke test that proves the full path or fails with an actionable diagnostic.

Repair loop:

1. Define smoke tests for Run pipeline, Upload footage, Reset and rerun, Send to re-edit, Approve draft, Delivery to Discover.
2. Mark which tests can run in CI and which are manual/operator-only.
3. Add diagnostics for external-service failures.
4. Store smoke results in docs or PR checklists before merging future changes.

## Cleanup opportunities

1. Keep `/api/operator/pipeline/run` only as a documented compatibility alias.
2. Consolidate operator API response contracts so mobile screens do not invent local meanings.
3. Keep future privileged/operator reads behind the operator API boundary.
4. Re-run the Discover smoke loop when validating GAP-011.
5. Keep QA-blocked drafts on the persistent re-edit loop until they pass QA or reach manual reject/review after `max_attempts`.

## Next recommended repair order

1. GAP-012 — QA-blocked persistent re-edit loop real-environment validation.
2. GAP-009 — operator API response contract consolidation.
3. GAP-010 — legacy route alias removal policy.
4. GAP-011 — real end-to-end validation.

## Audit maintenance rule

Every future app-pipeline PR should update this file when it changes the status of a gap, adds a new gap, or closes a cleanup item.

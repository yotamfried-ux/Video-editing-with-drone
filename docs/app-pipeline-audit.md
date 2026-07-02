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

## Open gaps

### GAP-007 — Open PR #45 belongs to a Discover-specific loop

Severity: medium.

Area: Discover, smoke diagnostics, database defaults.

Problem:

- PR #45 is still open and addresses Discover diagnostics and reel expiry behavior.
- It should not be mixed into the current operator app-pipeline fixes without review.

Root cause:

- Discover smoke work is related to delivery outcome but is a separate subsystem from operator action dispatch and pipeline status.

Target invariant:

- Discover fixes should be validated as their own loop with database migration review and smoke checks.

Repair loop:

1. Review PR #45 against current `main` after PRs #46-#55.
2. Confirm the migration is still needed and safe.
3. Run or document the Discover smoke checks.
4. Validate operator diagnostics remain behind operator auth.
5. Merge or close PR #45 based on current relevance.

### GAP-008 — README and deployment docs are behind the actual architecture

Severity: medium.

Area: documentation, onboarding, operations.

Problem:

- Older docs still describe the project mostly as a Python Drive pipeline.
- The actual system now includes mobile operator app, Next.js API, Supabase tracking, GitHub Actions dispatch, delivery, and Discover.

Root cause:

- Architecture evolved faster than top-level docs.

Target invariant:

- The root README describes the current architecture and points to deeper contracts instead of duplicating stale details.

Repair loop:

1. Audit README, DEPLOYMENT, and docs for stale route names, old run commands, and missing mobile/API concepts.
2. Rewrite the top-level overview around app -> API -> workflows -> Python -> Drive/Supabase -> app.
3. Link to focused docs instead of copying low-level details everywhere.
4. Validate route names and workflow names against current code.

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

1. Review PR #45 separately under a Discover-specific loop.
2. Keep `/api/operator/pipeline/run` only as a documented compatibility alias.
3. Remove stale README sections that imply the system is only a local Python pipeline.
4. Consolidate operator API response contracts so mobile screens do not invent local meanings.
5. Keep future privileged/operator reads behind the operator API boundary.

## Next recommended repair order

1. GAP-007 — review PR #45 under a Discover-specific loop.
2. GAP-008 — README and deployment documentation cleanup.
3. GAP-009 — operator API response contract consolidation.
4. GAP-010 — legacy route alias removal policy.
5. GAP-011 — real end-to-end validation.

## Audit maintenance rule

Every future app-pipeline PR should update this file when it changes the status of a gap, adds a new gap, or closes a cleanup item.

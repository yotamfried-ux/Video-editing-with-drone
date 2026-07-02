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

- The re-edit flow has similar feedback drift and should be audited next.

## Closed or superseded gaps

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

### GAP-001 — Live singleton status can conflict with durable run history

Severity: high.

Area: mobile operator status, `pipeline_status`, `pipeline_runs`, `delivery_runs`.

Problem:

- The app has a single live `pipeline_status` row and separate durable run tables.
- A singleton row cannot distinguish recent or overlapping operator actions.
- The operator can see progress from a different action than the run they just started.

Root cause:

- Live progress is global while operator actions are run-scoped.

Target invariant:

- Every operator action should be explainable from a durable run row.
- Singleton progress may exist, but it must be clearly marked as global or tied to the latest durable run.

Repair loop:

1. Map all reads of `pipeline_status`, `pipeline_runs`, and `delivery_runs` in the mobile app.
2. Add or adjust an operator API status route if direct table access is no longer acceptable.
3. Make the UI prefer durable run rows when explaining operator actions.
4. Use singleton status only for generic live progress, with copy that prevents run confusion.
5. Validate by starting different operator actions and confirming the UI does not mix statuses.
6. Update `docs/operator-pipeline-contract.md`.

### GAP-002 — Re-edit action likely has the same feedback drift approval had

Severity: high.

Area: mobile Review screen, `POST /api/operator/reprocess`, pipeline run tracking.

Problem:

- The Review screen tells the operator that re-edit will happen on the next pipeline run.
- The API path creates tracking records and starts a workflow, so the app should display the actual result.

Root cause:

- Mobile UI treats operator actions as fire-and-forget and does not consistently consume response metadata.

Target invariant:

- Every operator action that creates a run returns a run identifier, and the app surfaces that identifier or routes the operator to the relevant status card.

Repair loop:

1. Inspect the reprocess API response body and failure modes.
2. Add a typed mobile response for reprocess.
3. Show a message based on the actual API result, not a generic future-run message.
4. Include the created pipeline run prefix when available.
5. Verify API failure is not displayed as success.
6. Update the Review action documentation.

### GAP-003 — Upload footage flow needs a real app-to-pipeline smoke test

Severity: high.

Area: mobile upload, upload session route, Drive RAW folder, pipeline start route.

Problem:

- The app creates a Drive upload session, uploads bytes directly to Drive, then starts the pipeline.
- This path crosses app, API, Drive, GitHub Actions, and Supabase without one repeatable smoke test.

Root cause:

- External-service state is split across several systems and cannot be proven by web deployment checks alone.

Target invariant:

- A file uploaded from the app appears in RAW, is visible to the pipeline, creates a tracked pipeline run, and is either moved to PROCESSED after processing or fails loudly without being skipped in the future.

Repair loop:

1. Add an operator-only diagnostic or manual smoke checklist for upload-to-run.
2. Confirm upload creates the file in the expected RAW folder.
3. Confirm the pipeline lists the file regardless of MIME-type quirks.
4. Confirm the created `pipeline_runs` row is updated by the workflow.
5. Confirm Drive move behavior after PR #47 with app-uploaded files.
6. Document the smoke loop.

### GAP-004 — Mobile type-check is not clearly enforced by CI

Severity: medium-high.

Area: mobile CI, PR readiness.

Problem:

- Vercel checks validate web/API deployment, but mobile TypeScript can regress unless a separate mobile check runs.

Root cause:

- Mobile app lives in the same repo but may not have a required validation workflow.

Target invariant:

- Any PR that changes `mobile/` should run mobile type-check at minimum.

Repair loop:

1. Inspect GitHub Actions and mobile package scripts.
2. Add or update CI so mobile changes run the mobile type-check command.
3. Keep the workflow lightweight.
4. Validate with a mobile-only PR.
5. Document mobile validation in the operator app contract or deployment guide.

### GAP-005 — Direct Supabase access from mobile may be wider than needed

Severity: medium-high.

Area: mobile Supabase client, `pipeline_status`, operator authorization boundary.

Problem:

- Some operator status data is read directly from Supabase while other operator data goes through the API.
- This creates inconsistent security and debugging boundaries.

Root cause:

- The app evolved from direct status polling to privileged operator API routes without consolidating the read model.

Target invariant:

- Privileged operator screens should consistently use the API boundary unless a table is intentionally public and documented as safe.

Repair loop:

1. Identify every direct Supabase read in `mobile/`.
2. Classify each read as public, operator-only, or obsolete.
3. Move operator-only reads behind API routes.
4. Keep public reads only with explicit RLS and documentation.
5. Validate that the app works without undocumented direct table access.

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

1. Review PR #45 against current `main` after PRs #46-#48.
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

Root cause:

- The repo has separate mobile and web-api packages without shared contract definitions.

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

Root cause:

- Backward compatibility was added correctly, but no expiry or owner was documented.

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

Root cause:

- The system spans services that are difficult to validate with unit tests alone.

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
5. Prefer durable run rows over global singleton status for operator-facing explanations.
6. Add mobile validation to CI before treating mobile PRs as fully verified.

## Next recommended repair order

1. GAP-002 — re-edit response and operator feedback drift.
2. GAP-001 — status model mismatch between singleton progress and durable run history.
3. GAP-003 — upload-to-run smoke test.
4. GAP-004 — mobile type-check enforcement.
5. GAP-007 — review PR #45 under a Discover-specific loop.
6. GAP-008 — README and deployment documentation cleanup.

## Audit maintenance rule

Every future app-pipeline PR should update this file when it changes the status of a gap, adds a new gap, or closes a cleanup item.

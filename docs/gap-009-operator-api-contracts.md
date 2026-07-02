# GAP-009 — Operator API response contracts

Status: fixed by the operator API contract consolidation PR.

## Original problem

Mobile operator screens and hooks defined response interfaces locally. API routes returned response shapes independently. This made drift easy: a route could change a field name or partial-success shape without a single source of truth for the mobile app.

## Repair performed

- Added `docs/operator-api-contracts.md` as the response-shape source of truth.
- Added `mobile/src/features/operator/types/contracts.ts` as the mobile TypeScript mirror.
- Updated mobile operator consumers to import named contract types from the shared mobile contract file.
- Covered pipeline dispatch/reset/status/runs, upload, reprocess, drafts, approval, delivery status, reels, support, analytics, and Discover diagnostics.
- Updated `docs/operator-pipeline-contract.md` so future response-shape changes must update the contract docs and mobile type mirror together.

## Deliberate design choice

A true shared package imported by both `web-api` and `mobile` was not introduced in this pass. The repository is not currently organized as a workspace, and importing root/shared code into Expo can create Metro and EAS build risk.

The low-risk enforcement layer is therefore:

1. Web-api route shape documented in `docs/operator-api-contracts.md`.
2. Mobile mirror in `mobile/src/features/operator/types/contracts.ts`.
3. Mobile consumers import those named types.
4. Mobile Check type-checks all mobile changes.

## Additional drift fixed

The Reels re-edit flow now consumes `ReprocessSubmitResponse` and displays the returned `pipeline_run_id`. It no longer says the work waits for the next unrelated pipeline run.

## Future rule

Any operator API route response change must update both:

- `docs/operator-api-contracts.md`
- `mobile/src/features/operator/types/contracts.ts`

The reviewer must also search for `operatorFetch<` and verify mobile consumers use named contract types rather than local response interfaces.

## Main audit note

Updating `docs/app-pipeline-audit.md` was attempted but blocked by the tool during this pass. This dedicated document preserves the GAP-009 closure record and should be reflected in the main audit when the tool allows it.

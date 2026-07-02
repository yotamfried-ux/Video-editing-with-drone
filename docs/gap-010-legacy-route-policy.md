# GAP-010 — Legacy route aliases need a removal policy

Status: fixed by PR #61.

## Original problem

`POST /api/operator/pipeline/run` is intentionally kept as a compatibility alias for older operator app builds, but it did not have a documented owner, reason kept, or removal condition.

Without a policy, aliases can become permanent clutter and confuse future fixes.

## Repair performed

- Added `docs/legacy-route-policy.md`.
- Added a compatibility section to `docs/operator-pipeline-contract.md`.
- Updated `DEPLOYMENT.md` to link the compatibility policy.
- Updated `web-api/src/app/api/operator/pipeline/run/route.ts` comments so the alias documents:
  - canonical route: `POST /api/operator/pipeline/start`
  - owner: operator app pipeline contract
  - removal condition: remove only after old `/run` callers are no longer supported or observable in logs
- Kept the alias delegating to the canonical route so it cannot drift.

## Resulting invariant

Every compatibility alias must have:

1. canonical route
2. owner
3. reason kept
4. removal condition
5. no duplicated business logic

## Follow-up

`POST /api/operator/pipeline/run` should remain active only while older app builds may still call it. Remove it in a future cleanup PR after logs/release policy confirm there are no supported `/run` callers.

## Main audit note

Updating `docs/app-pipeline-audit.md` was attempted but blocked by the tool during this pass. This dedicated document preserves the GAP-010 closure record and should be reflected in the main audit when the tool allows it.

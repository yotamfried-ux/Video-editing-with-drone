# Resilient R2 upload retry plan

Date: 2026-07-20
Status: implementation, final CI, P1 review fixes, and fallback self-review complete; merge, production API deployment, EAS publication, and physical retest pending.

## Physical finding

During a real 20-file Android SD-card upload, 19 files failed. Most errors were DNS failures resolving the Cloudflare R2 host; one upload reached 63% and timed out after 60 seconds. The pipeline was not run.

## Required behavior

- [x] Copy each external-storage source into app cache once per manual upload action.
- [x] Request a fresh presigned URL immediately before each file attempt.
- [x] Retry each failed transfer automatically up to three times with delays.
- [x] Reuse a stable client upload ID so retries overwrite the same R2 object instead of creating duplicates.
- [x] Generate and persist a client batch ID before the first initialization request, so a lost response cannot split retries across batches.
- [x] Prevent a new selection from replacing unresolved failed items and accidentally unblocking the pipeline.
- [x] Keep one external file active at a time.
- [x] Add one-tap **Retry all failed** after connectivity is restored.
- [x] Keep individual Retry controls.
- [x] Block pipeline start while any selected upload is unverified.
- [x] Preserve the 20-video batch selection limit.
- [x] Add deterministic mobile/API/R2 contract coverage.
- [x] Mobile and Web API type-checks passed.
- [x] Operator Smoke, External Storage Upload, Resilient Upload, Surf Ride, Edit Context, and Source Evidence checks passed for code commit `aced2ce5e3492f13f45c7a7e0e450537eaca5396`.
- [x] Both P1 review findings were fixed and their outdated review threads were resolved.
- [x] CodeRabbit's final full review was rate-limited; a focused fallback self-review found no additional blocking issue in the six-file final diff.
- [ ] PR #188 is merged to `main`.
- [ ] The Web API change is deployed to production so resilient initialization and stable retry keys are live.
- [ ] The Android JavaScript update is published through EAS Update.
- [ ] Physical retest proves recovery from a temporary network interruption without duplicate R2 objects.

## Safety

This change never starts the pipeline automatically. The user must still explicitly start a run after all selected files show Verified at 100% and after the human ground-truth list is recorded.

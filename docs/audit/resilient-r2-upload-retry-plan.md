# Resilient R2 upload retry plan

Date: 2026-07-20
Status: implementation prepared; CI, review, merge, EAS publication, and physical retest pending.

## Physical finding

During a real 20-file Android SD-card upload, 19 files failed. Most errors were DNS failures resolving the Cloudflare R2 host; one upload reached 63% and timed out after 60 seconds. The pipeline was not run.

## Required behavior

- [x] Copy each external-storage source into app cache once per manual upload action.
- [x] Request a fresh presigned URL immediately before each file attempt.
- [x] Retry each failed transfer automatically up to three times with delays.
- [x] Reuse a stable client upload ID so retries overwrite the same R2 object instead of creating duplicates.
- [x] Keep one external file active at a time.
- [x] Add one-tap **Retry all failed** after connectivity is restored.
- [x] Keep individual Retry controls.
- [x] Block pipeline start while any selected upload is unverified.
- [x] Preserve the 20-video batch selection limit.
- [x] Add deterministic mobile/API/R2 contract coverage.
- [ ] Mobile and Web API type-checks pass.
- [ ] Operator Smoke and Resilient Upload checks pass.
- [ ] PR review has no unresolved findings.
- [ ] Merge and EAS publication complete.
- [ ] Physical retest proves recovery from a temporary network interruption without duplicate R2 objects.

## Safety

This change never starts the pipeline automatically. The user must still explicitly start a run after all selected files show Verified at 100% and after the human ground-truth list is recorded.

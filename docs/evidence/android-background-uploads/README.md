# Android background uploads — qualification evidence

This directory records how the durable Android background-upload feature (PR #255) was qualified.
It never claims qualification by itself: the authoritative result is the
`Android Background Upload Qualification` workflow run named in the PR description, whose
`bgq-qualification-summary-<run_id>` artifact (`qualification-summary.md/json`) is produced by
`scripts/background_upload_evidence.py summarize` and is only `Qualified: YES` when every lifecycle scenario
passed **and** its independent evidence proves exactly-once behaviour.

## TDD record

| step | evidence |
|---|---|
| Native core RED (types missing, 113 compile errors) | `native-core-RED.txt` |
| Native core GREEN | `scripts/run_native_upload_unit_tests.sh` → `OK (42 tests)`; CI job "pure-JVM engine tests" |
| Mutation check (engine resends acknowledged parts → 2 tests fail) | run during development, reverted |
| JS hand-off RED (module missing) → GREEN | `mobile/src/features/operator/lib/backgroundUploadClient.test.ts` |
| Contract RED (workflow/runner missing) → GREEN | `scripts/test_background_upload_contract.py` |
| Evidence checks RED → GREEN | `scripts/test_background_upload_evidence.py` |

## Scenarios (one emulator each, 3 videos ≥ 100 MiB = ≥ 7 multipart parts per video, one stable batch)

| scenario | OS perturbation | proves |
|---|---|---|
| foreground-baseline | none | normal upload, notification, gate probes |
| home-background | `KEYCODE_HOME`; app never reopened until the batch completes | continues in background |
| screen-off | `KEYCODE_SLEEP` / `WAKEUP` | continues with screen off |
| process-death-resume | `run-as … kill -9` while backgrounded, no relaunch | WorkManager resumes from the durable ledger |
| relaunch-reconcile | process kill, cold launch | UI reconciles durable progress |
| network-recovery | Wi-Fi and mobile data off → on (`svc`; airplane mode took the emulator adb transport offline) | no progress offline, automatic resume, never shown as failed |
| worker-restart-retry | two forced process kills + network flap | restarts reuse acknowledged parts |

Every scenario additionally asserts: exactly one `source_uploads` row and one R2 object per video (Supabase +
boto3 listing of `raw/<batch>/`, no open multipart uploads), part rows `1..N` once each, no acknowledged part
`PUT` twice (device event log), pipeline start rejected (HTTP 409, no run created) while incomplete, and the
batch accepted by `assert_upload_batch_ready` only when all files are verified with confirmed cleanup.

## Known boundaries

* Android Settings → Force stop blocks all scheduled work by OS design; the feature guarantees reconciliation
  and resume on the next launch (`reconcileBackgroundUploads` → `resumeEligibleBackgroundUploads`).
* The gate-acceptance check evaluates the route's own SQL predicate (`assert_upload_batch_ready`) read-only. A
  real `/pipeline/start` dispatch is intentionally not performed because it would launch a production pipeline
  run on test footage; the *rejection* path is exercised against the real route.
* Gallery (single-PUT) uploads are unchanged; only the SD / USB multipart path moved to the native worker.
* If `ForegroundServiceStartNotAllowedException` is raised (Android 12+, background start without an exemption)
  the durable job still runs as plain WorkManager work without the notification.

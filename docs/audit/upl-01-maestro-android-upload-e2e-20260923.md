# UPL-01 — Android gallery upload E2E on Maestro (2026-09-23)

UPL-01 was moved from a hand-written ADB driver (`uiautomator dump` + XML grep + fixed coordinates such as `tap 180 420` + `sleep`) to deterministic Maestro flows. Independent backend verification is kept. This is the first UPL-01 run whose upload reached the backend: before this change, Supabase held **zero** `upl01*` rows from the 7 earlier runs.

## Identity

| Item | Value |
|---|---|
| Branch / PR | `claude/keen-feynman-mkxbgp` / #219 (draft) |
| Application SHA (passing run) | `0045034206384721145cae21ff4128c6b4f7b774` |
| Workflow run | [35897304446](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35897304446) — job `107304318804`, conclusion **success** |
| Runner / device | `ubuntu-24.04`, `reactivecircus/android-emulator-runner@v2`, API 35 `google_apis` x86_64, `pixel_2`, KVM |
| App build | Expo SDK 52 debug APK (checkpoint cache), JS from Metro at the same SHA, validation-only `EXPO_PUBLIC_UPL01_OPERATOR_BYPASS=1` |
| Tool | Maestro CLI 2.10.0 (GitHub release zip, analytics disabled) |
| API deployment | Vercel production `dpl_AQRsHbLMrRAVGQqJ1EmjPWvpwWSe` = `main@128ba39`. This PR does not change `web-api/`, so the tested API is production. |
| Fixture | synthetic `testsrc` + sine MP4, 640x360, 4 s, **66989 bytes**, generated per run, never committed |

## Results

| Capability | Status | Evidence |
|---|---|---|
| Seed fixture into MediaStore (`addMedia`) | **PASS** | `00-seed-media` passed. It replaces `adb push` + `MEDIA_SCANNER_SCAN_FILE`, which Android ignores on API 29+. |
| Operator reaches Settings → Pipeline via stable ids | **PASS** | `testID`s `operator-secret-input`, `operator-secret-save`, `pipeline-upload-gallery` are exposed as resource-ids (visible in the captured hierarchy). |
| System Photo Picker selection (Android 13+) | **PASS** | Selected by `…providers.media.module:id/icon_thumbnail` resource-id, with no coordinates. |
| Negative: upload without operator secret | **PASS** | Alert `Some uploads failed`; the item is `Failed` with `Operator secret not set`. Supabase showed **0** rows from this attempt (read-only query, run 35895173989). The passing run's exactly-one-row check confirms it again. |
| Negative: picker cancelled | **PASS** | Silent no-op: no upload row, no alert, and the upload button is idle again. The exactly-one-row check confirms no backend write. |
| Negative: media permission denied | **NOT APPLICABLE (API 35)** | In expo-image-picker 16.0.6, `getMediaLibraryPermissions()` returns an empty array on API ≥ 33, so the request resolves as granted with no dialog, and the Photo Picker needs no runtime permission. The case applies only to API ≤ 32. |
| Positive: gallery upload, operator-visible result | **PASS** | Alert `Uploaded to queue`; the item row is `Verified · 100%` (`upload-item-status-verified`). |
| Positive: authoritative DB state | **PASS** | Harness verdict `UPL-01 backend verification: PASS`. My own Supabase read found exactly one row: `id 8f247d64-a30e-446e-87c9-413e3acd77a2`, `client_upload_id gallery_1790185670996_0_q3bj0h0jnz`, `batch_id batch_2026-09-23T17-47-51_m5i18j57`, `status verified`, `upload_protocol single_put`, `source_size_bytes = verified_size_bytes = 66989`, `source_size_evidence client_declared`, `verified_at 2026-09-23 17:47:54Z`. |
| Positive: exact R2 object | **PASS** | The harness called the production verify API with the row's `storage_key` (`raw/batch_2026-09-23T17-47-51_m5i18j57/2026-09-23T17-47-51_1000000016.mp4`) and required `ok/exists/storage_backend=r2/size=66989/upload_id/upload_status=verified`. Vercel runtime logs for that deployment show 1 `/api/operator/upload` and 2 `/api/operator/upload/verify` requests (the app's and the harness's) at 17:47:40–17:48:10Z. |
| Repeatability | **PARTIAL** | One green run on the final head. A second dispatch on the same head was queued for FLAKY classification; its result is recorded in PR #219. |

## Findings

1. **Original filename is not preserved on the Photo Picker path (OPEN, product decision).** The app received `1000000016.mp4`, a MediaStore id, and that is what `source_filename` and the `storage_key` suffix store. It is not yet isolated whether Maestro's `addMedia` MediaStore insert or the picker/expo `fileName` causes it. The harness records `source_filename_preserved` rather than asserting it, until the product decides whether operator filenames (e.g. `DJI_0001.MP4`) must survive.
2. **Harness defects fixed on the way.** Each was classified from the Maestro evidence first and given a regression in `scripts/test_upl01_maestro_contract.py`:
   - The APK checkpoint hit also skipped `setup-node` and `npm ci`, so Metro could not start (`Cannot determine the project's Expo SDK version`). This came from the original workflow.
   - Row assertions ran without scrolling; the rows render below the fold and under the debug LogBox banner.
   - Filename-based correlation broke on the MediaStore display name. Correlation now uses a gallery client id + exact fixture bytes + the run window.
3. **Triage-host gap.** GitHub Actions artifact downloads (`*.blob.core.windows.net`) are blocked from the Claude Code cloud host. The runner therefore prints a secret-scrubbed failure summary (failed command, Maestro reason, final screen labels) into the step log and job summary.

## What this does not prove

- A synthetic 4 s 640x360 file proves transport and bookkeeping only. It says nothing about 4K/30 source handling, tracking, identity or editing quality.
- An emulator PASS does not cover physical devices, SD/USB (`Choose videos from SD / USB`, the multipart path), real-device permission UX, low storage, or network interruption.
- `EXPO_PUBLIC_UPL01_OPERATOR_BYPASS` skips login and biometric entry. It is a validation-only entry point, not an auth mechanism and not evidence that authentication works. A regression fails if it appears in any EAS profile or another workflow.
- Not covered by this PR: interrupted upload, API 5xx, storage verification failure (`size_mismatch` / 409), and duplicate `client_upload_id` retry semantics. The verifier's handling of these backend states is unit-tested, but the app journeys are not exercised yet.

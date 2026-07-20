# Direct SD / USB upload — implementation audit

Date: 2026-07-19
PR: #183
Status: implementation, targeted contract, mobile type-check, operator smoke validation, and fallback self-review complete; merge, deployment, and physical-device validation pending.

## Product requirement

An operator using the Android app must be able to choose a folder on a connected SD card or USB storage device and upload its videos directly into the current SportReel RAW batch, without first copying the clips into Google Photos or the phone gallery.

## Implementation plan and evidence

- [x] Keep the existing gallery upload path and label it explicitly.
- [x] Add an Android system directory picker through Expo FileSystem Storage Access Framework.
- [x] Enumerate the selected folder and accept supported video extensions only.
- [x] Reuse the existing upload initialization, shared `batch_id`, per-file progress, R2 verification, and retry path.
- [x] Copy external `content://` sources into app cache only immediately before upload.
- [x] Limit external-storage work to one file at a time to avoid retaining several large temporary videos on the phone.
- [x] Delete every temporary cache copy in `finally`, including after a failed upload.
- [x] Add `scripts/test_external_storage_upload_contract.py`.
- [x] Add the dedicated `External Storage Upload Check` workflow; its targeted contract passed on PR #183.
- [x] Mobile Check is green (`npm ci`, `npm run type-check`).
- [x] Operator Smoke Check is green, including the updated shared upload-queue/storage contract.
- [x] PR review has no unresolved comments. CodeRabbit's full final review was rate-limited, so a focused fallback self-review was completed and all earlier outdated threads were resolved.
- [ ] Change is merged to `main`.
- [ ] The installed Android app has received the updated JavaScript bundle.
- [ ] A physical test with the user's phone, card reader, and SD card proves folder selection and verified upload.

## Safety boundaries

- This change must not start a pipeline run automatically.
- A real pipeline run still requires explicit user approval.
- The existing three-worker gallery upload flow remains unchanged.
- External-storage uploads use one worker because each source is temporarily copied from its SAF URI before the existing upload task consumes it.
- The temporary copy is an implementation bridge for Android `content://` access; the operator does not need to import the source into the gallery or manage a permanent phone copy.
- Selecting a folder scans that folder only. If clips are nested, the operator must choose the folder that directly contains them.


## Physical-test finding — 2026-07-19

The Android Storage Access Framework screen grants access to a folder; it does not select individual files. The first implementation immediately uploaded every supported video in that folder. The user's real card-reader test proved this behavior was not sufficient.

Follow-up implementation:

- [x] Keep the folder permission step so the app can access connected SD / USB storage without a new native dependency.
- [x] Stage the videos found in that folder instead of uploading immediately.
- [x] Show an in-app checkbox list with Select all, Clear, and Upload selected controls.
- [x] Preserve the existing sequential external-file cache copy, R2 verification, progress, retry, and manual pipeline-start behavior.
- [ ] Follow-up CI is green.
- [ ] Follow-up PR is merged and published through EAS Update.
- [ ] Physical retest proves only checked videos are uploaded.

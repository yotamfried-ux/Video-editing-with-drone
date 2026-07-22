# SportReel operational-readiness audit

Date: 2026-07-21  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Baseline inspected: `main` at merge commit `e853fb843ed34adfdc8692d19ab9a560cb0a2d54` (PR #190)  
Status: **open — implementation foundations exist, but the next production-style experiment still has entry blockers and the product vision is not yet proven end to end**

This file is the authoritative, consolidated readiness audit for the operator app, R2 upload path, GitHub Actions pipeline, Supabase state, perception/tracking, 4K rendering, QA, Review, Delivery, Discover, payments, and the real-footage evidence required by the product vision.

Historical implementation details remain in the focused audits under `docs/audit/` and in Git history. When a focused audit conflicts with this file about whether a gap is still open, this file controls until both are updated in the same PR.

## 1. Product outcome and closure rule

The source of truth remains `README.md` → **Product vision — source of truth**:

> Every distinct athlete with at least one complete, visible, usable action receives a personal, silent, publishable social-media reel centered on that athlete, or an explicit evidence-backed hard rejection.

For surfing, every complete readable usable wave must appear exactly once. Other people may remain visible when the featured athlete stays identifiable, continuous, central, and owns the action. A GitHub Actions success, a rendered file, or an LLM response is not sufficient proof.

Three readiness levels are used:

1. **Foundation implemented** — code and deterministic checks exist.
2. **Experiment entry ready** — the exact deployed app/API/workflow/database/storage stack can safely run the next evidence-producing experiment.
3. **Product gap closed** — the end-to-end checklist passed with real services, real Android behavior where applicable, real footage, preserved artifacts, and visual review.

A gap may be marked closed only when every checkbox in its **Mandatory end-to-end closure checklist** is checked and linked evidence is recorded beneath it. Green CI alone never closes a mobile-storage, external-service, footage-quality, identity, delivery, or payment gap.

## 2. Evidence rules for checking a box

Every checked item must name the evidence that proves it. Acceptable evidence includes:

- PR and exact commit SHA.
- CI workflow URL and final conclusion.
- Vercel production deployment tied to the exact commit.
- EAS update/build ID installed on the tested Android device.
- Supabase migration record plus read-only schema/data verification.
- R2 object key, `HEAD` result, object size, multipart upload metadata, or lifecycle evidence.
- GitHub Actions run ID, jobs, and relevant log excerpts.
- Durable `pipeline_runs`, `delivery_runs`, upload, QA, or payment row identifiers without exposing secrets.
- Android physical-test record, including network interruption/app restart/SD or USB behavior.
- Pipeline diagnostic artifact and direct visual inspection of final videos.

Not acceptable as closure evidence:

- “The code looks correct.”
- A preview deployment when production behavior is being claimed.
- A single successful HTTP response without downstream state verification.
- A screenshot without the corresponding endpoint/workflow/database/storage evidence.
- A synthetic fixture standing in for a required real-footage or real-device test.
- A successful upload response without object-size verification.
- A successful dispatch response without a correlated workflow run.
- Any secret value pasted into an audit, PR, issue, screenshot, or log.

## 3. Current verified baseline

The following foundations are present on the inspected `main` baseline:

- The mobile operator app is a control surface; heavy processing remains in GitHub Actions/Python.
- R2 keys are batch-scoped under `raw/<batch_id>/...`.
- Upload currently uses one signed `PUT` per complete file, followed by server-side `HEAD` verification.
- Gallery uploads can run concurrently; SD/USB uploads are copied one complete file at a time into app cache before the same full-file upload.
- The mobile app is pinned to Expo SDK `~52.0.28` and `expo-file-system ~18.0.10`.
- `POST /api/operator/pipeline/start` creates a durable `pipeline_runs` row, forwards `pipeline_run_id` and optional `batch_id` through `repository_dispatch`, and marks accepted dispatches as `workflow_dispatched`.
- `.github/workflows/pipeline-run.yml` scopes R2 processing by `RAW_BATCH_ID`, requires perception, uploads diagnostics, and verifies QA re-edit task persistence.
- The centered-athlete, silent-output, publishable-manifest, final-QA, 4K/30, contain-first, mandatory-perception, and no-app-biometrics contracts have deterministic coverage.
- PR #190 is merged, but its focused audit still records live migration, deployment, performance, tracker-quality, and real-footage closure work as pending.
- The QA-blocked operator action exists, but a fresh real re-edit run after the R2 requeue fix has not yet proved a terminal QA verdict.
- Direct SD/USB individual selection is implemented and published, but the final physical retest proving that only checked files upload is still open.
- Structured operator feedback exists, but the real feedback-to-database-to-next-run learning loop is not production-validated.

## 4. Readiness summary

| Gap | Priority | Current state | Blocks the next production-style evidence run? |
|---|---:|---|---|
| GAP-013 — Resumable multipart R2 upload | P0 | Single full-file PUT; retry restarts the file | Yes |
| GAP-014 — Durable Android source access and restart recovery | P0 | SD/USB file is copied in full to cache; upload state is not durable | Yes |
| GAP-015 — Durable batch/session/athlete upload manifest and verified-run gate | P0 | `batch_id` exists, but durable upload membership and semantic grouping are incomplete | Yes |
| GAP-016 — Dispatch, workflow, run, and operator-status correlation | P0 | Dispatch acceptance is explicit; real correlated transition is not yet proven | Yes |
| GAP-017 — Real perception/tracker quality and identity stability | P0 | Mandatory CV exists; difficult-footage metrics and tuning are pending | Yes |
| GAP-018 — Cross-source athlete grouping and duplicate control | P0 | Canonical IDs/diagnostics exist; real grouping and `reel_group_id` lineage are incomplete | Yes |
| GAP-019 — 4K/30 visual-quality and performance budget | P0 | Synthetic media contract passes; measured generation loss and production cost are pending | Yes |
| GAP-020 — Product-vision real-run proof | P0 | Contract/CI implemented; real visual production evidence pending | The evidence run closes it |
| GAP-021 — QA-blocked re-edit reaches a terminal verdict | P1 | App/task path exists; post-R2-fix terminal rerun unconfirmed | Required before claiming robust Review |
| GAP-022 — Review → Approve → Delivery → Discover → payment fulfillment | P1 | Components exist; full immutable-key/idempotent flow unproven | No for editing-only experiment; yes for full product readiness |
| GAP-023 — Production deployment, database migration, and environment parity | P0 | Exact live main/EAS/migration state is not fully verified | Yes |
| GAP-024 — Durable feedback/evaluation/learning loop | P2 | Capture foundation exists; durable replay learning is incomplete | No for next evidence run |
| GAP-025 — API contract drift and legacy route retirement | P2 | Typed mirrors exist; automatic cross-package drift prevention and alias retirement remain open | No for next evidence run |

## 5. Entry gate for the next production-style experiment

Do not start the next vision-validation run until all entry items below are checked:

- [ ] The audit PR is merged and `main` contains the current gap/closure definitions.
- [ ] The exact `main` commit under test is deployed to Vercel Production and the production domain resolves to that commit.
- [ ] The exact mobile build/update under test is installed and its EAS build/update ID is recorded.
- [ ] Required Supabase migrations are applied in version order and verified against the live project.
- [ ] The live project no longer contains the app-user biometric fields/buckets/RPCs scheduled for removal.
- [ ] The upload path used by the experiment supports durable multipart resume and does not restart a large file from byte zero after a transient failure.
- [ ] A real Android large-video test proves bounded-memory part reads and no required whole-file cache copy.
- [ ] Every selected file belongs to one durable batch/session record and reaches `verified` with exact size before pipeline start is enabled.
- [ ] Pipeline start is blocked while any intended batch file is pending, uploading, paused, completing, failed, or size-mismatched.
- [ ] A no-op or small controlled run proves `pipeline_run_id` and `batch_id` correlate app → API → GitHub Actions → Supabase → app status.
- [ ] The workflow preflight prints the resolved detector model, tracker, stride/image size, storage backend, batch ID, and pipeline run ID without leaking secrets.
- [ ] All affected deterministic checks and final-head CI are green.
- [ ] CodeRabbit actionable findings are resolved, or a documented focused self-review is complete.
- [ ] The source footage, expected athletes/actions/waves, and required artifact list are frozen before the run so success criteria cannot be changed afterward.

## 6. Detailed open gaps

### GAP-013 — Resumable multipart R2 upload

**Priority:** P0  
**Area:** mobile upload, Vercel web-api, Cloudflare R2, retry/abort/verification.

**Verified current state**

- `web-api/src/lib/r2-storage.ts` creates a single signed `PUT` URL.
- `mobile/src/app/(operator)/pipeline.tsx` uploads the whole file with `createUploadTask`.
- Automatic retry requests a new upload session and resends the whole file.
- `POST /api/operator/upload/verify` verifies object existence, but the current mobile request does not provide the original source size as a required equality check.
- Large 4K video can therefore lose all progress after a network interruption.

**Official design basis**

- Cloudflare R2 upload methods and multipart limits: https://developers.cloudflare.com/r2/objects/upload-objects/
- Cloudflare R2 multipart object API: https://developers.cloudflare.com/r2/api/workers/workers-api-reference/
- Cloudflare R2 S3 compatibility: https://developers.cloudflare.com/r2/api/s3/api/
- AWS SDK multipart uploader configuration: https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/Package/-aws-sdk-lib-storage/Interface/Configuration/
- AWS S3 multipart commands: `CreateMultipartUploadCommand`, `UploadPartCommand`, `CompleteMultipartUploadCommand`, and `AbortMultipartUploadCommand` from https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/client/s3/

Cloudflare defines multipart as the appropriate path for video, large files, parallelism, and resumability. Parts must be 5 MiB–5 GiB, all non-final parts must be the same size, at most 10,000 parts are allowed, and only failed parts should be retried. Exact part `ETag` values are required for completion. AWS documents the same command sequence and that memory use is bounded approximately by `queueSize × partSize`.

**Mandatory end-to-end closure checklist**

- [ ] A tracked Supabase migration creates the durable multipart upload schema.
- [ ] The web-api creates multipart uploads through the official R2 S3-compatible API and returns `upload_id`, canonical `r2_key`, `part_size_bytes`, and protocol version.
- [ ] The server issues short-lived signed URLs scoped to one `upload_id` and `part_number`.
- [ ] Every non-final part is the configured uniform size and at least 5 MiB.
- [ ] The total part count cannot exceed 10,000.
- [ ] The client stores the exact returned `ETag` and `part_number` for every completed part.
- [ ] Completion sends all parts sorted by ascending `PartNumber`.
- [ ] A failed part is retried without retransmitting successful parts.
- [ ] Client cancellation and unrecoverable failure call abort.
- [ ] Abort waits for or reconciles in-flight part requests and verifies that no active parts remain.
- [ ] Incomplete uploads have an explicit cleanup policy in addition to R2's default lifecycle.
- [ ] `HEAD Content-Length` equals `source_size_bytes` before the upload becomes `verified`.
- [ ] Multipart final ETag is not incorrectly treated as the source-file MD5.
- [ ] A deterministic contract test covers part sizing, ordering, exact ETags, single-part retry, complete, abort, and size mismatch.
- [ ] A real R2 integration test uploads and reconstructs a large video successfully.
- [ ] A network interruption proves only the missing/failed part is resent.
- [ ] Evidence is attached: R2 key, upload ID prefix, part ledger, retries, final size, cleanup result, CI run, and Android test record.

### GAP-014 — Durable Android source access and restart recovery

**Priority:** P0  
**Area:** Expo FileSystem, Android Storage Access Framework, SD/USB, process restart, memory.

**Verified current state**

- The installed code uses Expo SDK 52 and legacy `FileSystem.copyAsync`/`createUploadTask`.
- SD/USB `content://` sources are copied in full into app cache before upload.
- Upload state is held in React component state, so process death or app restart cannot reliably resume.
- The physical retest proving only selected external videos are uploaded remains open.

**Official design basis**

- Expo FileSystem `FileHandle`, offset, repeated `readBytes`, and `close`: https://docs.expo.dev/versions/v55.0.0/sdk/filesystem/
- Expo latest FileSystem architecture and legacy API status: https://docs.expo.dev/versions/latest/sdk/filesystem/
- Android shared documents and directory access: https://developer.android.com/training/data-storage/shared/documents-files
- Android persistable URI permissions: https://developer.android.com/reference/android/content/Intent#FLAG_GRANT_PERSISTABLE_URI_PERMISSION
- Expo DocumentPicker cache-copy behavior: https://docs.expo.dev/versions/latest/sdk/document-picker/

The current app is below the pinned Expo documentation version used for the proposed `FileHandle` design. The implementation must first prove that the required random-access API works on the project's pinned SDK, or perform a controlled Expo upgrade with a new native build. It must not assume that current documentation is available in Expo 52.

**Mandatory end-to-end closure checklist**

- [ ] An explicit compatibility decision is recorded: either prove `FileHandle` behavior on Expo 52 or upgrade Expo through a dedicated, tested PR.
- [ ] Any Expo upgrade passes native dependency compatibility review, mobile tests, Android build, and installed-device smoke.
- [ ] Large source files are read in bounded parts using an official random-access/stream API rather than `bytes()`, `bytesSync()`, base64, or a whole-file cache copy.
- [ ] The file handle offset is set deterministically for each part.
- [ ] Each read returns at most the configured part size.
- [ ] Every handle is closed in `finally` on success, retry, pause, cancellation, and error.
- [ ] Durable state survives app restart and restores the same source, upload ID, completed-part ledger, and next missing part.
- [ ] Android persistable URI permission is requested/stored where the source provider supports it.
- [ ] If the SD/USB device is removed, state becomes `source_unavailable` without aborting or losing completed parts.
- [ ] Reconnecting the same source resumes; selecting a different file with the same name is rejected by fingerprint/size checks.
- [ ] The final physical selection retest proves unchecked external videos are not uploaded.
- [ ] A real Android memory profile shows that memory does not scale with complete video size.
- [ ] A 4K video test covers: pause, network loss, force-close, app restart, device removal, reconnection, and completion.
- [ ] Temporary files, if any are still needed for a limited compatibility fallback, are bounded, documented, and removed in `finally`.
- [ ] Evidence is attached: Expo/EAS version, device/build ID, source URI class, memory measurement, restart log, part ledger, and final R2 size.

### GAP-015 — Durable batch/session/athlete upload manifest and verified-run gate

**Priority:** P0  
**Area:** upload model, Supabase, mobile session state, R2 key layout, pipeline admission.

**Verified current state**

- R2 objects are scoped by `batch_id`.
- `activeBatchId` lives in mobile component state and can be lost.
- A batch does not yet have a durable authoritative manifest describing intended files, source sizes, upload states, session purpose, or athlete grouping.
- `batch_id` is a transport boundary, but it is not yet a complete `session_id`/`athlete_id` business grouping contract.
- Pipeline start can be requested without a server-side proof that all intended files are verified.

**Official design basis**

- Supabase database migrations: https://supabase.com/docs/guides/deployment/database-migrations
- Supabase Row Level Security: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase secure backend/service-role boundary: https://supabase.com/docs/guides/database/secure-data
- Cloudflare R2 prefixes and object upload behavior: https://developers.cloudflare.com/r2/objects/upload-objects/
- GitHub `repository_dispatch` payload contract: https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event

**Mandatory end-to-end closure checklist**

- [ ] A durable `upload_batches` record exists with `batch_id`, optional `session_id`, optional explicit `athlete_id`/operator grouping, state, expected file count, verified file count, created/updated timestamps, and owner/operator metadata.
- [ ] Each selected source has one durable upload record containing the fields required by GAP-013/014.
- [ ] RLS is enabled for exposed tables; service-role writes remain server-side only.
- [ ] The app restores an unfinished batch after restart instead of silently creating a new one.
- [ ] Adding more files to the same batch is explicit and preserves existing verified membership.
- [ ] A file cannot belong to two active batches accidentally.
- [ ] Filename reuse cannot overwrite or impersonate another source; canonical R2 keys remain immutable.
- [ ] The server calculates batch readiness from durable rows, not mobile state.
- [ ] `Run pipeline now` is rejected with an actionable response unless all intended files are `verified` and size-matched.
- [ ] The dispatch payload contains the authoritative `batch_id` and `pipeline_run_id`.
- [ ] The workflow lists only `raw/<batch_id>/` and records the exact input object list before processing.
- [ ] An unrelated batch remains untouched by run, reset, re-edit, and cleanup operations.
- [ ] A real 2–3 video batch proves one dispatch processes every intended file exactly once and no unrelated file.
- [ ] The experiment records whether the batch represents one athlete, one session with multiple athletes, or another explicit grouping; the pipeline never infers this from filenames.
- [ ] Evidence is attached: batch row, upload rows, R2 listing before/after, dispatch payload fields, run artifact input manifest, and reset isolation result.

### GAP-016 — Dispatch, workflow, run, and operator-status correlation

**Priority:** P0  
**Area:** Vercel endpoint, GitHub API/Actions, Supabase `pipeline_runs`, mobile status.

**Verified current state**

- PR #83 makes GitHub's 204 response visible as `workflow_dispatched`.
- A 204 proves GitHub accepted the event; it does not prove that a workflow run was created or started.
- The row initially links to the workflow page, not a specific GitHub Actions run URL/ID.
- The latest real app-triggered transition after the fix has not been recorded in this consolidated audit.

**Official design basis**

- GitHub create repository dispatch event and token permissions: https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event
- GitHub `repository_dispatch` workflow behavior: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#repository_dispatch
- GitHub Actions workflow concurrency: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
- Vercel deployment checks for repository-dispatch workflows: https://vercel.com/docs/deployment-checks

**Mandatory end-to-end closure checklist**

- [ ] Vercel Production has `GITHUB_REPO` and a token with the documented minimum working repository permission; only variable names are recorded.
- [ ] The workflow file exists on the default branch and listens to the exact event type.
- [ ] API timeout, non-204, 404, 422, and network-error paths produce durable actionable terminal states.
- [ ] A successful dispatch changes `dispatching` → `workflow_dispatched`.
- [ ] The actual workflow writes its `github.run_id`, run URL, attempt, and commit SHA back to the same `pipeline_runs` row.
- [ ] The same row changes to `running` before expensive processing.
- [ ] Stage/progress updates remain attached to the same run ID.
- [ ] Concurrency queueing is represented honestly; a queued run is not shown as processing.
- [ ] Completion writes one terminal state: `succeeded`, `failed`, `no_input`, or another documented terminal result.
- [ ] `pipeline_status` stale detection falls back to the latest durable run without rewriting history.
- [ ] App, API response, GitHub run, durable row, live status, and diagnostic artifact agree on run ID, batch ID, commit, and outcome.
- [ ] A forced dispatch failure and a forced workflow failure both surface correctly in the app.
- [ ] Evidence is attached: production deployment commit, pipeline run row snapshots, GitHub Actions run URL, logs, app screenshots, and stale-status test.

### GAP-017 — Real perception/tracker quality and identity stability

**Priority:** P0  
**Area:** Ultralytics, BoT-SORT, detector/tracker sidecars, identity, crop authority.

**Verified current state**

- Production workflow requires perception and defaults to Ultralytics plus BoT-SORT.
- Synthetic contracts prove required fields and fail-closed behavior.
- Difficult real footage has not yet established acceptable fragmentation, identity continuity, or runtime cost.
- Prior audits record severe track fragmentation and unresolved same-athlete split/two-athlete merge risk.

**Official design basis**

- Ultralytics tracking mode, BoT-SORT, camera-motion compensation, and optional Re-ID: https://docs.ultralytics.com/modes/track/
- NVIDIA DeepStream tracker/Re-ID and occlusion/ID-switch limits: https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html
- Google Gemini video sampling limitations for fast motion: https://ai.google.dev/gemini-api/docs/video-understanding
- Google Cloud Video Intelligence object tracking: https://cloud.google.com/video-intelligence/docs/feature-object-tracking

Gemini's default video sampling can miss fast sports detail, so it cannot be the sole identity/crop proof. Tracker IDs also are not automatically ground truth: occlusion, spray, distance, moving cameras, and look-alike athletes can produce ID switches or new IDs.

**Mandatory end-to-end closure checklist**

- [ ] Workflow preflight records detector model, tracker config, confidence thresholds, stride/image size, FPS assumption, device, and Re-ID setting.
- [ ] Sidecar schema records frame/time, bbox, confidence, track ID, visibility, and source dimensions for every analyzed event.
- [ ] Missing/invalid/zero-detection evidence fails closed with a clear diagnostic.
- [ ] A representative difficult surfing set includes distance, spray, occlusion, same-wave surfers, camera motion, entry/exit, and visually similar athletes.
- [ ] Raw track count, stitched track count, median track duration, tracks under two seconds, lost/reacquired intervals, and ID switches are measured.
- [ ] One athlete is not split into multiple canonical athletes without explicit unresolved evidence.
- [ ] Two different athletes are not merged.
- [ ] Featured-athlete ownership remains stable through temporary occlusion and another surfer entering the action.
- [ ] Crop decisions use measured tracker evidence and never an LLM hint alone.
- [ ] Every false merge, false split, ID switch, and uncertain interval is included in the artifact.
- [ ] Frame stride, input size, thresholds, camera-motion compensation, and optional Re-ID are tuned from measured evidence rather than guessed.
- [ ] Detector/tracker wall time, CPU minutes, memory, and failure rate per source video are recorded.
- [ ] A negative fixture and real negative case prove the pipeline blocks unsafe identity instead of guessing.
- [ ] Evidence is attached: sidecars, fragmentation summary, visual overlays/sample frames, tuning record, runtime metrics, and final identity decisions.

### GAP-018 — Cross-source athlete grouping and duplicate control

**Priority:** P0  
**Area:** multiple clips per athlete, canonical identity, reel grouping, duplicate moments/drafts.

**Verified current state**

- Stable athlete IDs, candidate ledger, duplicate diagnostics, and final manifest checks exist.
- The duplicate metric can still false-positive because drafts do not carry a durable `cluster_id`/`reel_group_id`.
- Detection currently reports likely duplicates but does not safely merge/drop them.
- The desired product behavior is one primary reel per eligible athlete, with additional Parts only for real duration pressure.

**Official design basis**

- Ultralytics tracking and Re-ID concepts: https://docs.ultralytics.com/modes/track/
- NVIDIA target re-association limits: https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html
- Google Cloud instance-level tracking: https://cloud.google.com/video-intelligence/docs/feature-object-tracking
- OpenAI evaluation resources for explicit datasets/graders: https://developers.openai.com/api/reference/resources/evals

**Mandatory end-to-end closure checklist**

- [ ] A durable run-scoped `cluster_id` or `reel_group_id` is written into draft metadata, candidate ledger, coverage report, and publishable manifest.
- [ ] All source appearances contributing to one primary reel trace to that group ID.
- [ ] Same-athlete clips across multiple files merge only with strong evidence; labels or filenames are never identity proof.
- [ ] Distinct athletes with similar appearance remain separate.
- [ ] Same physical action uploaded twice is represented once.
- [ ] Distinct actions/waves by the same athlete remain separate.
- [ ] Multiple Parts share the same athlete/group identity and exist only because complete actions exceed 90 seconds.
- [ ] Duplicate detection distinguishes intentional Parts from duplicate primary outputs.
- [ ] Any automatic merge/drop rule is introduced only after tracker-fragmentation evidence passes GAP-017.
- [ ] Positive and negative cross-source eval fixtures define expected grouping and duplicate outcomes.
- [ ] A real multi-file same-athlete batch produces one primary reel without duplicate actions.
- [ ] A real multi-athlete session produces separate primary reels with no identity crossover.
- [ ] Evidence is attached: input list, group lineage, similarity/track evidence, duplicate decisions, manifest, and visual output review.

### GAP-019 — 4K/30 visual-quality and performance budget

**Priority:** P0  
**Area:** FFmpeg rendering, 4K output, Actions runtime, R2 transfer.

**Verified current state**

- Synthetic FFmpeg validation proves 2160x3840, 30 fps, H.264 High Profile, yuv420p, BT.709, silent output, and contain framing.
- Generation loss, emergency-crop quality, Actions time/cost, output size, and transfer reliability are not measured on representative footage.

**Official design basis**

- YouTube recommended upload encoding settings: https://support.google.com/youtube/answer/1722171
- FFmpeg filters, including scale/pad/crop, SSIM, PSNR, and libvmaf: https://ffmpeg.org/ffmpeg-filters.html

**Mandatory end-to-end closure checklist**

- [ ] Every final Part is verified by `ffprobe`: 2160x3840, 30 fps, progressive H.264 High Profile, yuv420p, BT.709, MP4 fast-start, and no audio stream.
- [ ] Source and output frame rates match the product contract.
- [ ] Default `contain` output preserves the complete sharp source frame.
- [ ] Every tracked crop records measured necessity and never exceeds the documented zoom cap.
- [ ] VMAF and SSIM are measured for representative contain output.
- [ ] VMAF/SSIM or an explicitly justified equivalent comparison is measured for at least one emergency-crop case.
- [ ] Any metric threshold used for blocking is calibrated with visual review; no universal threshold is invented.
- [ ] Per-stage wall time, total Actions minutes, CPU/memory, source size, output size, download duration, upload duration, and retry count are recorded.
- [ ] No hidden downscale, frame-rate reduction, skipped perception, or shortened action occurs to meet runtime.
- [ ] Workflow timeout has measured headroom for the representative batch.
- [ ] R2 multipart upload handles the resulting large files without full restart.
- [ ] Final files are reviewed at native resolution on a representative display.
- [ ] Evidence is attached: ffprobe report, VMAF/SSIM output, framing decisions, timing/cost report, R2 sizes, and visual review notes.

### GAP-020 — Product-vision real-run proof

**Priority:** P0  
**Area:** analyzer, identity, selection, editor, QA, manifest, app status, visual output.

**Verified current state**

- The business contract and deterministic gates are implemented and merged.
- Real footage has not yet proved the complete vision after the latest 4K/perception/biometric changes.

**Official design basis**

- Gemini video understanding and timestamp limitations: https://ai.google.dev/gemini-api/docs/video-understanding
- Gemini structured output and application-side semantic validation: https://ai.google.dev/gemini-api/docs/structured-output
- OpenAI Evals and graders: https://developers.openai.com/api/reference/resources/evals and https://developers.openai.com/api/reference/resources/graders
- Anthropic evaluation guidance: https://docs.anthropic.com/en/docs/test-and-evaluate/eval-tool

**Mandatory end-to-end closure checklist**

- [ ] The exact comparison footage and expected athlete/action/wave inventory are recorded before execution.
- [ ] The run uses the exact production-deployed commit and records it in durable state/artifacts.
- [ ] Every distinct eligible athlete receives exactly one primary publishable reel or an explicit evidence-backed hard rejection.
- [ ] Every complete readable usable surf wave appears exactly once or has an explicit hard-reject reason.
- [ ] Another surfer on the same wave does not remove a valid ride while the target remains central and continuous.
- [ ] Team-sport group context remains allowed while action ownership stays attributable.
- [ ] No reel changes featured athlete mid-action or mixes identity ownership.
- [ ] No physical action appears twice across files, drafts, or Parts.
- [ ] Good social/editorial moments are not silently lost; every detected candidate has a selected/rejected decision reason.
- [ ] No complete action is cut at the beginning, peak, or outcome.
- [ ] Every Part is independently understandable, silent, vertical, 4K/30, at most 90 seconds, and technically publishable.
- [ ] Final QA has explicit real evidence and every FAIL blocks approval.
- [ ] `publishable_reel_manifest.json`, athlete coverage, candidate ledger, selection audit, source evidence, draft trace, QA trace, media report, and status snapshots are present and mutually consistent.
- [ ] GitHub conclusion, durable `pipeline_runs`, live operator state, R2 objects, and app UI agree.
- [ ] Every final video is visually inspected, not only metadata-checked.
- [ ] False positives, false negatives, identity splits/merges, crop errors, missed moments, and repairs are recorded.
- [ ] A deliberate business-gate failure proves stale success cannot survive in GitHub/Supabase/app state.
- [ ] Evidence is attached: run URL, commit, batch, complete artifact bundle, R2 keys, status rows, screenshots, and visual review record.

### GAP-021 — QA-blocked re-edit reaches a terminal verdict

**Priority:** P1  
**Area:** QA task persistence, Review UI, R2 requeue, rerun, max attempts.

**Verified current state**

- A QA-blocked task can appear in Review, block approval, and be promoted to `pending`.
- A prior real run exposed the R2 `processed/` → `raw/` requeue key bug.
- The fix has deterministic coverage, but a fresh real run has not yet proved source requeue, note injection, QA rerun, and terminal result.

**Official design basis**

- Supabase migrations and durable schema history: https://supabase.com/docs/guides/deployment/database-migrations
- Supabase secure service-role boundary: https://supabase.com/docs/guides/database/secure-data
- Cloudflare R2 object/S3 operations: https://developers.cloudflare.com/r2/api/s3/api/
- GitHub workflow concurrency: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

**Mandatory end-to-end closure checklist**

- [ ] A final QA FAIL writes one durable `qa_blocked` request with defects, blocked reasons, source identities, attempt count, and max attempts.
- [ ] Review lists the task, disables approval, shows actionable reasons, and preserves operator notes.
- [ ] “Send QA notes to re-edit” promotes the same task atomically and creates one correlated pipeline run.
- [ ] Requeue resolves the source from its actual canonical current R2 key, not a stale prefix or filename.
- [ ] Only the intended source/batch is requeued.
- [ ] The next run consumes the pending request once and records injected QA/operator notes.
- [ ] Re-edit applies a traceable repair rather than silently rerunning unchanged output.
- [ ] QA reruns on the regenerated file.
- [ ] PASS becomes normal approvable Review state.
- [ ] FAIL creates/updates the next blocked task with incremented attempts.
- [ ] Reaching max attempts becomes explicit manual review/reject, not an infinite loop.
- [ ] Workflow failure leaves a recoverable truthful task state.
- [ ] A real end-to-end app-triggered re-edit reaches PASS, another QA-blocked state, or manual reject with complete evidence.
- [ ] Evidence is attached: original draft/key, task row snapshots, dispatch/run URL, requeue log, notes, repair trace, QA trace, final state, and app screenshots.

### GAP-022 — Review → Approve → Delivery → Discover → payment fulfillment

**Priority:** P1  
**Area:** Review approval, immutable storage identity, delivery workflow, Discover, Stripe.

**Verified current state**

- Review, approval, delivery runs, Discover, checkout, webhook, and purchase foundations exist.
- The complete R2-backed flow has not been proven in one current-production end-to-end run.
- A success page or redirect alone cannot prove payment fulfillment.

**Official design basis**

- Stripe webhook signature verification and retries: https://docs.stripe.com/webhooks
- Stripe Checkout fulfillment and “perform only once” guidance: https://docs.stripe.com/checkout/fulfillment
- Stripe idempotent requests: https://docs.stripe.com/api/idempotent_requests
- Vercel Production versus Preview environments: https://vercel.com/docs/deployments/environments
- Supabase RLS/service-role security: https://supabase.com/docs/guides/database/postgres/row-level-security and https://supabase.com/docs/guides/database/secure-data

**Mandatory end-to-end closure checklist**

- [ ] Review lists the exact canonical `review/` R2 object key and protected watch URL.
- [ ] Missing, mismatched, QA-failed, or non-publishable authority blocks approval in API and app.
- [ ] Approval moves/copies the exact object from `review/` to `approved/` without filename-only authority.
- [ ] One durable `delivery_runs` row correlates approval, storage key, reel, run, and operator response.
- [ ] Delivery creates the intended Discover/preview/pending-payment state without exposing the full unpurchased file.
- [ ] Checkout uses the correct reel/purchase identity.
- [ ] Webhook verifies Stripe's signature from the raw request body.
- [ ] Fulfillment is idempotent for retries and concurrent calls.
- [ ] A Checkout Session is fulfilled only after confirmed paid state.
- [ ] Repeated webhook delivery does not duplicate purchase, delivery, email, or sold-state transitions.
- [ ] Failed webhook/delivery remains observable and recoverable.
- [ ] The purchased athlete can access the correct final reel; another user cannot.
- [ ] Expiry/download/share behavior matches the product contract.
- [ ] A Stripe sandbox test proves checkout, webhook, purchase, sold/fulfilled state, protected access, and retry idempotency.
- [ ] Evidence is attached: Review/approved R2 keys, delivery row, Discover reel, Stripe event/session IDs, purchase row, webhook delivery attempts, access-control tests, and app screenshots.

### GAP-023 — Production deployment, database migration, and environment parity

**Priority:** P0  
**Area:** Vercel Production, EAS, GitHub Actions, Supabase, secrets/config names.

**Verified current state**

- PR #190 is merged.
- Its audit records the destructive face-recognition-removal migration, exact Vercel/EAS deployment verification, live cleanup, and no-biometric smoke as pending.
- Vercel Preview success is not proof that Production uses the same commit or environment values.
- GitHub Actions secrets and Vercel environment variables are independent.

**Official design basis**

- Vercel environments: https://vercel.com/docs/deployments/environments
- Vercel deployment checks: https://vercel.com/docs/deployment-checks
- Vercel production deployment management: https://vercel.com/docs/deployments/managing-deployments
- Expo EAS Update: https://docs.expo.dev/eas-update/introduction/
- Supabase migrations: https://supabase.com/docs/guides/deployment/database-migrations
- Supabase RLS and service-role security: https://supabase.com/docs/guides/database/postgres/row-level-security and https://supabase.com/docs/guides/database/secure-data

**Mandatory end-to-end closure checklist**

- [ ] The exact `main` commit intended for testing is identified.
- [ ] Vercel Production is READY and the production domain is aliased to that exact commit.
- [ ] Production API smoke tests run against the production domain, not a PR Preview.
- [ ] Required Vercel variable names exist in Production: storage backend/R2, GitHub dispatch, Supabase, operator auth, Stripe, and other route dependencies; values are never exposed.
- [ ] Required GitHub Actions secret/variable names exist independently and storage preflight passes.
- [ ] The mobile build/update channel and runtime version are documented.
- [ ] The exact EAS update/build is installed on the Android device and verified from app metadata.
- [ ] Every tracked Supabase migration is applied in order and migration history is reconciled.
- [ ] `20260721_remove_face_recognition.sql` is backed up/approved, applied, and verified.
- [ ] Live tables, columns, RPCs, policies, and storage buckets contain no removed app-user biometric path.
- [ ] Registration, login, profile, Discover, checkout, payment, support, and delivery work without biometric fields.
- [ ] New upload-state tables have RLS and server-only service-role writes.
- [ ] Deployment rollback steps are documented and tested at least as a dry procedure.
- [ ] Evidence is attached: commit, Vercel production deployment, domain response, EAS ID, migration list/verification, schema checks, and no-biometric smoke results.

### GAP-024 — Durable feedback/evaluation/learning loop

**Priority:** P2  
**Area:** operator feedback, candidate ledger, replay evals, ranking, historical learning.

**Verified current state**

- Structured feedback buttons, API storage, prompt injection, missed-moment report, and additive editorial score exist.
- Real feedback-to-row-to-next-run prompt behavior is unverified.
- Candidate ledger is not durably queryable across historical runs.
- Feedback lacks precise source time-window linkage and does not yet safely alter selection/ranking behavior.

**Official design basis**

- OpenAI Evals and graders: https://developers.openai.com/api/reference/resources/evals and https://developers.openai.com/api/reference/resources/graders
- Anthropic evaluation tooling: https://docs.anthropic.com/en/docs/test-and-evaluate/eval-tool
- Supabase migrations/security: https://supabase.com/docs/guides/deployment/database-migrations and https://supabase.com/docs/guides/database/secure-data

**Mandatory end-to-end closure checklist**

- [ ] A real operator feedback action writes the expected durable row.
- [ ] The next eligible run records the exact normalized feedback evidence injected into analysis.
- [ ] Feedback is linked to immutable draft/storage identity, pipeline run, athlete/group, and source time window when known.
- [ ] Candidate ledger and selection decisions are stored durably across runs.
- [ ] Operator cards expose enough evidence to understand primary track, source window, duplicate risk, mixed-subject risk, and selection/rejection reason.
- [ ] A versioned evaluation dataset contains positive and negative examples from reviewed real runs.
- [ ] Deterministic graders cover identity, coverage, duplicates, technical compliance, and status truth.
- [ ] Model graders are limited to editorial/social-quality dimensions after deterministic gates.
- [ ] Ranker or selection changes are tested in replay before production activation.
- [ ] Offline comparison proves a change improves target metrics without reducing athlete/action recall.
- [ ] Rollback/version fields allow restoring the prior policy.
- [ ] Real-run monitoring records false positives, false negatives, missed moments, QA bypass, duplicate athletes, and operator corrections.
- [ ] Evidence is attached: feedback rows, prompt trace, durable ledger rows, eval dataset/version, grader results, before/after replay, and policy version.

### GAP-025 — API contract drift and legacy route retirement

**Priority:** P2  
**Area:** web-api/mobile TypeScript contracts, compatibility alias.

**Verified current state**

- web-api and mobile have typed mirrored operator contracts.
- They remain manually synchronized because the repository has no shared workspace/package.
- `/api/operator/pipeline/run` remains a compatibility alias without a complete retirement record.

**Official design basis**

- TypeScript project references: https://www.typescriptlang.org/docs/handbook/project-references.html
- npm workspaces: https://docs.npmjs.com/cli/v11/using-npm/workspaces
- Next.js route handlers: https://nextjs.org/docs/app/building-your-application/routing/route-handlers

**Mandatory end-to-end closure checklist**

- [ ] Every operator route and mobile consumer is listed in one machine-checkable contract inventory.
- [ ] Success, partial, and error response schemas are explicit.
- [ ] A build/test detects drift between mobile and web-api rather than relying only on a comment.
- [ ] The chosen solution is proportionate: shared package/workspace, generated schema/client, or deterministic mirror comparison.
- [ ] Authentication and rate-limit error contracts are included.
- [ ] Compatibility aliases have owner, purpose, callers, telemetry, and removal condition.
- [ ] Active mobile versions are checked before alias removal.
- [ ] `/api/operator/pipeline/run` is removed only after the documented release window and no-call evidence.
- [ ] Negative contract tests cover stale/unknown fields and unsupported old clients.
- [ ] Evidence is attached: contract artifact, drift-failure test, active-version/call evidence, and alias-removal PR when eligible.

## 7. Required experiment artifact bundle

Every production-style experiment must retain one bundle containing:

- exact repository commit, Vercel deployment, EAS build/update, workflow run, pipeline run, and batch IDs;
- durable upload batch and file rows, multipart part ledger, source sizes, R2 keys, and final verification;
- frozen expected athlete/action/wave inventory;
- detector/tracker preflight and sidecars;
- track fragmentation/identity summary;
- candidate decision ledger and selection audit;
- cross-source group/duplicate lineage;
- framing decisions;
- source evidence, draft trace, repair trace, and QA trace;
- athlete coverage and publishable reel manifest/gate result;
- ffprobe and visual-quality reports;
- per-stage runtime, resource, size, transfer, retry, and cost metrics;
- `pipeline_runs`, live status, reprocess task, delivery run, Discover/payment rows when applicable;
- final videos and written visual review;
- observed defects and the next result-loop decision.

The experiment is invalid for product-closure claims if required artifacts are missing, stale, or cannot be tied to the same commit/run/batch.

## 8. Recommended repair order

1. **GAP-013 + GAP-014 + GAP-015** — implement official multipart resume, durable Android source recovery, and a verified durable batch manifest.
2. **GAP-023** — deploy the exact current stack and apply/verify all live migrations, including biometric removal and upload-state schema.
3. **GAP-016** — run a controlled app dispatch and prove one correlated transition through GitHub Actions and Supabase.
4. **GAP-017 + GAP-018 + GAP-019** — preflight, measure, and tune tracking/identity, cross-source grouping, 4K quality, and runtime on difficult representative footage.
5. **GAP-020** — execute the frozen production-style experiment and review every artifact/video against the product vision.
6. **GAP-021** — exercise the QA-blocked re-edit loop to a real terminal verdict if the experiment produces a blocked draft; otherwise run a controlled blocked fixture against real services.
7. **GAP-022** — prove Review, approval, Delivery, Discover, Stripe fulfillment, and protected access end to end.
8. **GAP-024** — accumulate reviewed runs and activate durable replay learning only after evaluation evidence exists.
9. **GAP-025** — automate contract drift detection and retire the legacy route when active-client evidence permits it.

## 9. Audit maintenance rule

Every PR that changes upload, storage, batch semantics, dispatch, status, perception, identity, selection, rendering, QA, Review, Delivery, Discover, payment, deployment, database schema, or feedback behavior must update this file in the same PR.

A gap can move to **closed** only when:

- every mandatory checkbox is checked;
- each checkbox has direct evidence;
- final-head CI/review passed;
- the relevant production deployment/migration is verified;
- required real-device/real-service/real-footage validation passed;
- no contradictory audit remains open without an explicit explanation.

Do not delete closed gap history. Move it to a dated **Closed gaps** section with the closing PR, commit, evidence links, and any remaining monitoring obligation.

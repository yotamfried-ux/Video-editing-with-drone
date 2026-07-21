# Remaining gaps — official-reference audit

Date: 2026-07-21  
Repository: `yotamfried-ux/Video-editing-with-drone`  
PR: #191  
Status: **implementation evidence improved; production merge remains blocked by large-video upload architecture and live validation**

## Scope and rule

This audit re-checks the non-Stripe gaps that remained before PR #191. A gap is not marked closed merely because code exists or deterministic CI passes. Live database state, deployed commit identity, physical-device behavior, and real-footage product quality require their own evidence.

## Official references

### Ultralytics — tracking, BoT-SORT, ReID, and frame stride

- Tracking mode and tracker configuration: <https://docs.ultralytics.com/modes/track/>
- Official BoT-SORT defaults: <https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/trackers/botsort.yaml>
- Configuration reference (`vid_stride`): <https://docs.ultralytics.com/usage/cfg/>

Official implications:

- BoT-SORT is suitable for moving-camera footage because it includes global-motion compensation.
- Re-identification is disabled by default to reduce overhead, but Ultralytics documents enabling it when appearance cues are needed through occlusion or among look-alike subjects.
- `vid_stride` greater than one skips frames for speed at the cost of temporal resolution.

### Google Cloud Video Intelligence and NVIDIA DeepStream — identity evidence

- Google object tracking: <https://cloud.google.com/video-intelligence/docs/object-tracking>
- Google person detection: <https://cloud.google.com/video-intelligence/docs/feature-person-detection>
- NVIDIA tracker documentation: <https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html>

Official implications:

- Instance-level identity requires time-scoped boxes and track identifiers, not only a semantic description.
- Occlusion, camera movement, scale changes, and similar-looking people can cause ID switches and require temporal plus appearance evidence.

### Cloudflare R2 — direct and multipart upload

- Upload methods: <https://developers.cloudflare.com/r2/objects/upload-objects/>
- Presigned URLs: <https://developers.cloudflare.com/r2/api/s3/presigned-urls/>
- AWS SDK compatibility and signed `Content-Type`: <https://developers.cloudflare.com/r2/examples/aws/aws-sdk-js/>
- Error codes: <https://developers.cloudflare.com/r2/api/error-codes/>

Official implications:

- Single `PUT` is intended for small-to-medium objects, approximately under 100 MB.
- Cloudflare explicitly recommends multipart upload for video, large files, or any upload where resumability and reliability matter.
- Single `PUT` is not resumable and restarts the full object after an interruption.
- A presigned URL that includes `ContentType` requires the client to send the same `Content-Type` header.

### Expo — file access and release updates

- Expo FileSystem: <https://docs.expo.dev/versions/latest/sdk/filesystem/>
- Expo FileSystem legacy API: <https://docs.expo.dev/versions/latest/sdk/filesystem-legacy/>
- EAS Update deployment: <https://docs.expo.dev/eas-update/deployment/>

Official implications:

- The current app uses legacy upload APIs. They remain available through the legacy module but are not the forward-looking File/stream API.
- Production updates should be tested on a matching staging runtime and promoted from the same tested commit/bundle.

### Netflix VMAF and FFmpeg — generation-loss evidence

- Netflix VMAF repository: <https://github.com/Netflix/vmaf>
- VMAF with FFmpeg: <https://github.com/Netflix/vmaf/blob/master/resource/doc/ffmpeg.md>
- VMAF models, including 4K: <https://github.com/Netflix/vmaf/blob/master/resource/doc/models.md>

Official implications:

- VMAF/SSIM can measure perceptual and structural generation loss.
- Reference and distorted streams must be timestamp-aligned and compared at the intended viewing resolution.

### Supabase — migration deployment

- Database migrations: <https://supabase.com/docs/guides/deployment/database-migrations>
- CLI `db push` and `--dry-run`: <https://supabase.com/docs/reference/cli/v1/supabase-db-push>

Official implications:

- Schema changes should be tracked as migration files, tested through a reset, previewed with `db push --dry-run`, then applied through migration history rather than ad-hoc remote edits.
- A migration file in Git is not proof that the live project has applied it.

### Vercel — production deployment identity

- Deployment overview: <https://vercel.com/docs/deployments/overview>

Official implication:

- Production readiness requires verifying the production deployment, commit identity, build logs, and assigned production domain—not only a successful preview or repository check.

### GitHub Actions — durable evidence

- Workflow artifacts: <https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts>
- Job execution time: <https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time>

Official implications:

- Generated logs, reports, and test results should be uploaded as artifacts.
- Actual job duration and billable execution data must be read from the completed run; an estimated cost is not evidence.

## Gap matrix

| ID | Gap | Official comparison | PR #191 action | Closure state |
|---|---|---|---|---|
| CV-001 | Default BoT-SORT had ReID disabled | Ultralytics documents ReID as opt-in and useful for look-alike/occlusion cases | Added `config/trackers/sportreel_botsort_reid.yaml`; production default now uses BoT-SORT, moving-camera compensation, and `with_reid: true` | **Code/CI closable; real identity accuracy still open** |
| CV-002 | Resolved model/tracker/stride were invisible before processing | Reproducible evaluation requires explicit configuration | Added fail-closed preflight and JSON/job-summary evidence; custom perception commands must name the same model and tracker | **Implemented; needs first production artifact** |
| CV-003 | Tracker runtime and fragmentation were not measured automatically | GitHub artifacts and job timing should preserve measurements | Sidecars now record wall time, processed frames, sampling rate, and ReID state; diagnostics build a per-video benchmark/fragmentation report | **Implemented; real run pending** |
| CV-004 | Default `vid_stride=10` trades away temporal resolution | Ultralytics explicitly states that higher stride skips frames at a temporal-resolution cost | Stride is now printed and preserved as evidence; no unsupported claim that 10 is correct | **OPEN — tune on difficult footage** |
| CV-005 | ID switches and false merges lack ground truth | Google/NVIDIA describe identity as temporal instance evidence and warn about occlusion/appearance failures | Benchmark report explicitly leaves ID-switch and correctness fields for reviewed/labeled footage | **OPEN — real-footage review required** |
| UPLOAD-001 | Large 4K video uses one non-resumable `PUT` | Cloudflare recommends multipart for video/large/reliability-sensitive files and says single PUT must restart | Existing retry path remains safer for transient failures, but it is not multipart | **BLOCKS MERGE for production-ready large-video claim** |
| UPLOAD-002 | Presigned upload did not bind declared MIME type | Cloudflare SDK example signs `ContentType`, and client must send the exact header | R2 presigner now includes `content-type` in signed headers; route supplies the normalized MIME type | **Implemented; real R2 request pending** |
| UPLOAD-003 | Verification checks existence/length returned by R2, not equality with local bytes or checksum | R2 exposes integrity errors such as `BadDigest`; multipart parts have ETags | No false closure recorded | **OPEN — expected-size/checksum contract required** |
| UPLOAD-004 | No interrupted-network physical-device proof | Cloudflare's resumability distinction and Expo device APIs make this a runtime property | Deterministic retries remain covered; physical Android SD/USB test is not simulated as proof | **OPEN — device/network experiment required** |
| UPLOAD-005 | SD/USB copy failure could leave an item permanently `initializing` | Expo file access can fail before any network request and must surface a recoverable application state | Preparation now runs inside the guarded lifecycle; copy failures become `failed`, preserve error text, and expose retry | **Implemented; device proof pending** |
| VIDEO-001 | No measured generation loss on contain and emergency crop | Netflix documents VMAF/SSIM and timestamp alignment | Existing 4K/30 ffprobe fixture proves media format, not perceptual loss | **OPEN — VMAF/SSIM experiment required** |
| PAY-UNIT-001 | Historical `pricing.price_ils` rows could contain agorot while new code interprets major ILS | Payment boundaries must use unambiguous units; Supabase requires an applied versioned migration | Added `price_unit='major_ils_v1'`, a one-time legacy-agorot migration, fail-closed checkout, a sub-₪1,000 invariant, and schema verification | **Code complete; live migration proof open** |
| PAY-UNIT-002 | Meshulam analytics could store agorot while Stripe stores major ILS | Shared reporting fields require one unit | Meshulam validates provider minor units, then converts once to major ILS for analytics and uses the same idempotent event key | **Implemented; live payment proof open** |
| PAY-IDEMP-001 | Stripe checkout idempotency key was scoped only by reel | Reusing one key with different payer parameters can reject a valid new logical checkout | SecureStore key now scopes the checkout session to both reel and normalized payer identity | **Implemented; shared-device test pending** |
| DB-001 | Pending migrations are not live evidence | Supabase requires migration-history-backed deployment and supports dry run | Migration files remain versioned; no live mutation performed in this audit | **OPEN — dry-run, backup/approval, push, verify** |
| DEPLOY-001 | Production Vercel commit is not current | Vercel exposes production deployment commit/build/log identity | No deployment claim added | **OPEN — deploy/promote and verify exact SHA** |
| DEPLOY-002 | Mobile update identity is unverified | Expo recommends staging on matching runtime and promoting the tested bundle/commit | No EAS publication performed | **OPEN — staging device test and production promotion** |
| REAL-001 | No end-to-end representative-footage proof | All official tracker/quality guidance still requires evaluation on representative data | Required artifact list remains unchanged | **OPEN — production-style run and visual review** |
| VALUE-001 | Ranking/replay value has no measured baseline | Not closed by infrastructure documentation | No claim of completion | **OPEN — replay evaluation and product metrics** |

## Review findings fixed in this pass

The PR review found four defects that deterministic checks had not previously covered:

1. Existing `7900` pricing rows could be multiplied again and become a ₪7,900 charge.
2. Meshulam revenue could be recorded 100× larger than Stripe revenue in the shared analytics field.
3. SD/USB copy failures occurred before the upload error lifecycle and could leave the UI permanently busy.
4. A shared device could reuse another payer's pending Stripe idempotency key for the same reel.

Each finding now has both a code fix and a regression contract. The database-dependent unit fix remains fail-closed until its migration is applied and verified.

## Implemented in this pass

1. A project-owned BoT-SORT tracker configuration with ReID enabled.
2. A mandatory perception preflight that fails when production tracking is not BoT-SORT + ReID, validates custom command overrides, and records exact model/tracker/stride/image-size/device/version values.
3. Sidecar wall-time, processed-frame, effective-sampling, and ReID evidence.
4. An automatic `perception_benchmark_report.json` artifact with raw/canonical fragmentation and track-duration statistics.
5. R2 presigned upload URLs bound to the declared `Content-Type`.
6. Recoverable SD/USB preparation failure handling.
7. Explicit and migrated pricing units, Meshulam/Stripe reporting parity, and payer-scoped Stripe idempotency.
8. Deterministic contract coverage for the new evidence chain and the four review findings.

## Merge decision

PR #191 must **not** be described or merged as a production-ready end-to-end solution while `UPLOAD-001` remains unresolved. The current single-PUT implementation can retry an entire file, but Cloudflare's official guidance says video and reliability-sensitive large objects should use multipart upload. Typical 4K source footage can exceed the approximate 100 MB single-upload recommendation, so this is a product-path mismatch rather than an edge case.

A narrower merge is defensible only if the release is explicitly limited to small test files and production large-video upload remains disabled. That is not the current SportReel product goal.

## Required next implementation before merge

1. Add R2 multipart initiation, per-part upload, completion, and abort APIs with stable upload identity.
2. Upload fixed-size parts from the mobile app, persist completed part numbers/ETags, and resume only failed/missing parts after restart or connectivity loss.
3. Validate total byte size and completed object metadata before marking an item verified.
4. Add deterministic multipart contract tests, then run an Android SD/USB upload while interrupting and restoring connectivity.
5. Run the mandatory perception preflight and benchmark on difficult real surfing footage; record runtime, fragmentation, ID switches, and visual identity continuity.
6. Measure VMAF/SSIM for contain and emergency-crop outputs.
7. After explicit approval: dry-run/apply/verify Supabase migrations, deploy exact main SHA to Vercel, publish/test matching EAS staging runtime, and perform the full production-style run.

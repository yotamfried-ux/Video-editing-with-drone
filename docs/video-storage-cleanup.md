# Video storage cleanup (Operator "Clean Video Storage")

Purpose: before uploading a new game/batch, remove the previous job's video material so the next
pipeline run can never consume it. Supersedes the standalone Python script/workflow of PR #248
(its inventory/verification idea is kept in `scripts/video_storage_cleanup_e2e.py` as an
*independent* verifier).

## One shared service
`web-api/src/lib/video-storage-cleanup.ts` (pure logic) + `video-storage-cleanup-runtime.ts`
(R2/Supabase deps, run tracking) are used by both:

* `POST /api/operator/storage/clean` (Operator app, no GitHub Actions involved)
* `web-api/scripts/clean-video-storage.ts` + `.github/workflows/clean-video-storage.yml` (manual break-glass)

## API
| Method | Purpose |
|---|---|
| `GET /api/operator/storage/clean` | read-only preview: inventory + active DB counts + latest run |
| `POST /api/operator/storage/clean` `{confirmation:"DELETE_OLD_VIDEOS"}` | start a run (bounded ~40 s step) |
| `POST /api/operator/storage/clean` `{run_id}` | continue the same run until `status != running` |

Auth: `x-operator-secret` via `requireOperator` (same as every operator route). The body can never
name a bucket, prefix or key; scope is fixed server-side.

## Scope
Deleted (through `deleteR2Object`, S3 `AbortMultipartUpload`, Supabase Storage API — never SQL on `storage.objects`):
* R2 video-extension objects under `raw/ processed/ review/ approved/ pending_payment/ pending_uploads/ previews/`
* incomplete R2 multipart uploads
* Supabase Storage `reels` bucket video files

Kept: users/auth/profiles, `athlete_photos`, non-video R2 objects, `metadata/`, videos under unknown
prefixes (reported as `r2_unscoped_video_objects`, never deleted), secrets/config, payments/purchases,
`drafts`, `pipeline_runs`, `delivery_runs`, dedup audit rows.

## Active DB state (atomic RPC `neutralize_active_video_state`)
Historical rows are kept; only active references are made terminal:
* `source_uploads` uploading/paused/completing/verified/superseded/size_mismatch -> `aborted` (+`removed_at`, note)
  so exact-content dedup can never pick an old row as canonical for a new upload
* `upload_batches` collecting/uploading/ready/running -> `cancelled`, manifest cleared
* `reprocess_requests` pending/queued/qa_blocked -> `cancelled` so old sources are not re-queued
* `reels` published/viewed -> `expired`

The RPC refuses (`pipeline_active`) while a pipeline run/batch is live (activity within 7 h).

## Safety properties
* fail-closed: success is derived only from an independent re-inventory + active-state check
* idempotent: a second run on a clean system succeeds with 0 deleted
* resumable: each step recomputes remaining work from live storage
* single running cleanup enforced by a unique partial index on `video_storage_cleanup_runs`; every run is audited there
* storage failure, DB failure or failed verification => `status: failed`, UI never shows success

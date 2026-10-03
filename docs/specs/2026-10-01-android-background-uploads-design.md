# Durable Android background uploads — design

Date: 2026-10-01
Status: Approved

## Goal

SportReel video uploads must continue when the app moves to the background, the screen turns off, or the app process is closed. Interrupted uploads must resume from durable multipart state rather than restarting completed work. A pipeline run must never start from a partially uploaded batch.

## Existing foundation

The app already has stable batch IDs, a JS upload queue with retries, multipart upload APIs, a durable upload ledger, and the native `SportReelSourceReader` module. The missing boundary is execution: the JS queue owns the long-running upload, so Android may suspend it when the app is backgrounded.

## Architecture

Move long-running upload execution to Android native infrastructure while keeping React Native as controller/UI.

1. A user selection receives one stable `batch_id` before work starts.
2. JS persists the upload jobs and asks a native upload manager to enqueue the batch.
3. Android WorkManager owns durable scheduling. Long-running transfers run as foreground work with a visible upload notification.
4. The worker reads source bytes through the existing native source-reader path and uses the existing multipart API contract.
5. Multipart identity, completed part ETags, attempts, progress, and terminal state are persisted durably. Restarting the app or worker resumes the same upload rather than creating a second upload.
6. React Native observes the durable ledger and renders progress; it does not need to stay alive for transfer progress.
7. Network loss results in retry/backoff and WorkManager network constraints, not batch abandonment.
8. Pipeline start remains gated on every upload in the batch reaching verified state.

## Lifecycle contract

Uploads must survive:
- app backgrounding;
- screen off / device idle conditions allowed by Android foreground work;
- activity destruction;
- process death / user swiping the app away where Android permits scheduled work to continue;
- transient network loss;
- worker restart.

A device reboot may reschedule persisted WorkManager jobs. Android force-stop from system settings is an OS-level boundary: Android intentionally prevents background execution until the user launches the app again. On next launch SportReel must reconcile the durable ledger and resume eligible unfinished work.

## Foreground notification

Long-running uploads expose a persistent Android notification such as `SportReel — Uploading 17/53 videos`. Progress is derived from durable transfer state. Completion or terminal failure removes/updates the notification appropriately.

## Data integrity

- `batch_id` is immutable for a selected batch.
- Each source upload has one durable logical upload identity.
- Multipart retries reuse the existing multipart upload where safe.
- Already acknowledged parts are not uploaded again unless server reconciliation proves they are absent.
- Completion is idempotent.
- A retry/restart must not create duplicate `source_uploads` or duplicate R2 objects.
- Pipeline start requires the existing verified-batch gate; background execution cannot bypass it.

## Failure handling

Transient network/server errors retry with bounded exponential backoff. Authentication/validation errors fail closed and surface in UI. If local and server multipart state disagree, reconcile against server truth before resuming. A worker crash leaves the ledger resumable. No UI state alone is accepted as proof that an upload completed.

## Security

No R2 credentials or Supabase service credentials are stored on-device. The worker uses the existing authenticated API and signed/multipart contracts. Background support must not broaden arbitrary bucket/key access.

## Qualification

Automated contract/unit tests plus Android E2E simulations must cover:
1. foreground upload baseline;
2. background app while upload continues;
3. screen off while upload continues;
4. activity/app process termination and durable resume;
5. network disconnect/reconnect;
6. worker retry/restart;
7. multipart resume without re-uploading acknowledged parts;
8. no duplicate source rows or R2 objects after retries/restarts;
9. multiple videos in one stable batch;
10. pipeline start rejected before full batch verification and accepted only after all uploads verify;
11. UI progress reconciles correctly after relaunch;
12. notification lifecycle.

Tests must distinguish Android/emulator infrastructure failures from product failures and must not weaken the existing upload or verified-batch contracts.

## Success criteria

The feature is complete only with fresh evidence that a real Android build can begin a multi-video upload, leave/close the app, continue or durably resume it, survive network interruption, finish every object exactly once, restore accurate progress on relaunch, and expose the batch to pipeline start only after complete verification.
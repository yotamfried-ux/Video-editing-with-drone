# Durable Android Background Uploads Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SportReel multipart video uploads continue or durably resume across app backgrounding, screen-off, process termination, network interruption, and relaunch without duplicate uploads or premature pipeline starts.

**Architecture:** Keep the existing server multipart protocol and stable batch semantics, but move long-running transfer ownership from the React Native JS queue into an Android WorkManager foreground worker inside the existing `sportreel-source-reader` Expo module. Persist native job/part progress independently of the React context, reconcile with server multipart truth before every resume, and expose enqueue/status observation APIs back to React Native.

**Tech Stack:** React Native / Expo SDK 52, TypeScript, Kotlin, Android WorkManager + foreground notifications, existing R2 multipart Web API, Jest, Gradle, Maestro/GitHub Actions.

## Global Constraints

- Uploads must survive app backgrounding, screen off, activity destruction, process death/swipe-away where Android permits scheduled work, transient network loss, worker restart, and app relaunch.
- Android Settings force-stop remains an OS boundary; on next launch SportReel reconciles and resumes unfinished eligible jobs.
- No R2 or Supabase service credentials may be stored on-device.
- Reuse the existing multipart API and verified-batch pipeline gate; background support may not weaken either.
- `batch_id` remains stable for a complete user selection.
- Multipart completion and resume must be idempotent and must not create duplicate `source_uploads` or R2 objects.
- Acknowledged server parts are not re-uploaded unless reconciliation proves them absent.
- React Native is controller/UI only; upload correctness cannot depend on the JS runtime staying alive.
- Long-running work uses an Android foreground notification with durable progress.
- Tests must distinguish emulator/CI infrastructure failures from product failures and must not weaken existing upload contracts.

---

### Task 1: Native durable job store and module contract

**Files:**
- Modify: `mobile/modules/sportreel-source-reader/android/build.gradle`
- Modify: `mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/SportReelSourceReaderModule.kt`
- Create: `mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/BackgroundUploadStore.kt`
- Create: `mobile/modules/sportreel-source-reader/android/src/test/java/expo/modules/sportreelsourcereader/BackgroundUploadStoreTest.kt`
- Modify: `mobile/modules/sportreel-source-reader/src/SportReelSourceReaderModule.ts`

**Interfaces:**
- Consumes: selected `content://` URI, immutable `batchId`, filename, MIME type, source size, API base URL and short-lived/operator-auth request material already available to the app.
- Produces: `enqueueBackgroundUpload(job)`, `listBackgroundUploads()`, `getBackgroundUpload(localId)`, and `resumeEligibleBackgroundUploads()` native-module APIs; durable states `queued | uploading | retry_wait | completing | verified | failed`.

- [ ] **Step 1: Add focused failing tests**

Test native serialization/store behavior for: stable local ID, completed part persistence, retry state surviving store reconstruction, terminal verified state, malformed/corrupt record isolation, and two uploads sharing one `batchId` without sharing upload identity.

- [ ] **Step 2: Verify the relevant failure**

Run: `cd mobile && ./gradlew :sportreel-source-reader:testDebugUnitTest` after prebuild/module resolution as required by the repository.
Expected: tests fail because `BackgroundUploadStore` and native background APIs do not exist.

- [ ] **Step 3: Implement the minimum behavior**

Add WorkManager dependency. Implement an application-context-backed durable JSON/SharedPreferences store with serialized mutation. Store source URI, source metadata, server upload ID once allocated, storage key, part size/count, completed part ETags/sizes, attempt/error/status timestamps and batch ID. Extend the Expo module using application context rather than requiring `reactContext` for background-safe source access. Persist URI read permission when enqueueing where the provider grants it. Expose enqueue/list/get/resume APIs without starting transfer logic yet.

- [ ] **Step 4: Verify the focused pass**

Run native unit tests and `cd mobile && npm run type-check`.
Expected: store tests and TypeScript native interface type-check pass.

- [ ] **Step 5: Run affected integration check**

Run: `cd mobile && npx expo-modules-autolinking resolve --platform android` and native Kotlin compile.
Expected: `SportReelSourceReaderModule` resolves and compiles with WorkManager dependency.

- [ ] **Step 6: Commit the passing deliverable**

Commit only Task 1 files with message `feat: add durable native upload job store`.

### Task 2: WorkManager foreground multipart executor

**Files:**
- Create: `mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/BackgroundUploadWorker.kt`
- Create: `mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/BackgroundUploadHttpClient.kt`
- Create: `mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/UploadNotification.kt`
- Modify: `mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/SportReelSourceReaderModule.kt`
- Test: `mobile/modules/sportreel-source-reader/android/src/test/java/expo/modules/sportreelsourcereader/BackgroundUploadWorkerTest.kt`

**Interfaces:**
- Consumes: durable native job, existing `/api/operator/upload/multipart/start|status|part-url|record-part|complete|cleanup` contracts and `content://` random-access source.
- Produces: exactly-once logical multipart progress in the native store, foreground notification progress, WorkManager success/retry/failure result.

- [ ] **Step 1: Add focused failing tests**

Use fake HTTP/source/store boundaries to assert: server status is reconciled before uploading; completed server parts are skipped; a missing part is read at the exact byte offset and uploaded once; 408/429/5xx/network errors return retry without losing state; validation/auth 4xx fail closed; completion happens only when every expected part is recorded; a worker reconstructed from persisted state resumes; verified server status becomes terminal without re-upload; and notification counts reflect durable completed parts.

- [ ] **Step 2: Verify the relevant failure**

Run native unit tests.
Expected: failures because worker/client/notification executor are absent.

- [ ] **Step 3: Implement the minimum behavior**

Create a `CoroutineWorker` with `NetworkType.CONNECTED`, unique work keyed by logical upload ID, bounded exponential WorkManager backoff, and foreground service notification channel. Reimplement the existing TypeScript multipart protocol exactly: start idempotently when no server upload exists, status reconciliation, per-part signed URL, ranged content read, PUT, exact ETag record, complete, verified-size assertion, then cleanup evidence. Never persist R2 credentials. Treat retryable transport/408/429/5xx as `Result.retry()`, permanent 4xx/state mismatch/source mutation as durable failed state, and server `verified` as idempotent success. Update durable progress after every acknowledged server transition.

- [ ] **Step 4: Verify the focused pass**

Run native worker tests.
Expected: all resume/retry/idempotency/notification assertions pass.

- [ ] **Step 5: Run affected integration check**

Run Android Kotlin compile and existing `large-upload-foundation-check` contract suite.
Expected: native module compiles and existing multipart contracts remain green.

- [ ] **Step 6: Commit the passing deliverable**

Commit Task 2 files with message `feat: run multipart uploads in Android background worker`.

### Task 3: React Native handoff, reconciliation and pipeline gating

**Files:**
- Modify: `mobile/src/features/operator/lib/multipartUploadClient.ts`
- Modify: `mobile/src/features/operator/lib/multipartUploadLedger.ts`
- Modify: `mobile/src/features/operator/lib/uploadQueue.ts`
- Modify: `mobile/src/app/(operator)/pipeline.tsx`
- Modify: `mobile/src/features/operator/lib/uploadQueue.test.ts`
- Create: `mobile/src/features/operator/lib/backgroundUploadClient.test.ts`

**Interfaces:**
- Consumes: native enqueue/list/get/resume APIs and existing stable batch assignment.
- Produces: JS handoff to native ownership, reconciled UI progress after foreground/relaunch, and unchanged verified-batch pipeline-start contract.

- [ ] **Step 1: Add focused failing tests**

Assert: a large external source is enqueued once instead of being uploaded by a long-lived JS promise; all selected items retain one batch ID; relaunch reads native state and displays existing progress; duplicate enqueue returns existing logical job; verified native jobs reconcile to existing server/local cleanup semantics; failed jobs expose retryable/permanent state; pipeline start remains unavailable while any batch member is non-verified.

- [ ] **Step 2: Verify the relevant failure**

Run: `cd mobile && npm test -- --runInBand src/features/operator/lib/uploadQueue.test.ts src/features/operator/lib/backgroundUploadClient.test.ts`.
Expected: new background-handoff assertions fail against the current JS-owned multipart implementation.

- [ ] **Step 3: Implement the minimum behavior**

Change the large-upload path so JS inspects/assigns the stable batch, hands the job to native WorkManager and observes durable native state. Keep the existing TypeScript multipart implementation only as compatibility/reference until native qualification passes; do not run JS and native transfer concurrently for the same logical upload. Reconcile native state on Pipeline screen mount/app foreground. Render durable progress and retry/failure status. Keep server verified-batch gating authoritative before pipeline start.

- [ ] **Step 4: Verify the focused pass**

Run focused Jest tests and `npm run type-check`.
Expected: enqueue/relaunch/progress/gating tests pass.

- [ ] **Step 5: Run affected integration check**

Run existing mobile upload tests plus `scripts/test_large_upload_foundation_contract.py`, `scripts/test_multi_upload_batch_contract.py`, `scripts/test_upload_batch_verified_gate_contract.py`, and `scripts/test_exact_source_upload_dedup_contract.py` with the repository's existing PYTHONPATH convention.
Expected: no regression in dedup, stable batch or verified gate.

- [ ] **Step 6: Commit the passing deliverable**

Commit Task 3 files with message `feat: hand large uploads to durable Android worker`.

### Task 4: Android lifecycle qualification and CI evidence

**Files:**
- Create: `mobile/.maestro/background-upload/01-background.yaml`
- Create: `mobile/.maestro/background-upload/02-screen-off-resume.yaml`
- Create: `mobile/.maestro/background-upload/03-process-restart.yaml`
- Create: `mobile/.maestro/background-upload/04-network-recovery.yaml`
- Create: `scripts/test_background_upload_contract.py`
- Create: `.github/workflows/android-background-upload-qualification.yml`
- Modify: `.github/workflows/large-upload-foundation-check.yml`

**Interfaces:**
- Consumes: instrumented Android build, test upload fixtures, production-safe/test-scoped multipart API evidence, adb lifecycle/network controls and native durable status.
- Produces: CI artifacts containing lifecycle actions, progress snapshots, server upload/source-row counts, R2/object identity evidence, notification evidence and final verified-batch state.

- [ ] **Step 1: Add failing static/behavior contract**

Contract asserts WorkManager foreground worker exists, network constraint exists, unique work is keyed by logical upload identity, no R2/service secrets are embedded, pipeline gate remains present, and qualification workflow exercises lifecycle/network transitions.

- [ ] **Step 2: Verify the relevant failure**

Run: `python scripts/test_background_upload_contract.py` before wiring the workflow/evidence.
Expected: failure identifying missing qualification workflow/scenarios.

- [ ] **Step 3: Implement simulations**

Build/install the Android artifact, seed multiple uniquely named test videos, begin one stable batch, then separately exercise: Home/background with continued progress; screen off/on with continued/resumed progress; process kill then relaunch/reconcile; network disable/enable with retry/resume; worker retry; and multi-video completion. Capture notification/progress and server evidence. For every scenario assert no duplicate `source_uploads`, no duplicate storage key/object, acknowledged parts are not resent, UI progress matches durable/server state after relaunch, and pipeline start is rejected before all sources verify then allowed after full verification. Do not simulate Settings force-stop as a requirement; document it as the Android OS boundary and test relaunch reconciliation separately.

- [ ] **Step 4: Verify focused pass**

Run static contract plus Android E2E workflow.
Expected: all lifecycle scenarios pass with fresh artifacts and exact object/source counts.

- [ ] **Step 5: Run full affected qualification**

Run large-upload foundation, mobile/type-check/native compile, relevant security/contracts and Android background-upload qualification on the final head.
Expected: all relevant checks green; any emulator failure is rerun only after logs distinguish infrastructure from product behavior.

- [ ] **Step 6: Commit the passing deliverable**

Commit Task 4 files with message `test: qualify durable Android background uploads`.

## Unresolved externally observable decisions

None. The approved design fixes background behavior, foreground notification, resume semantics, force-stop boundary, retry behavior, deduplication and pipeline gating. Implementation must preserve the existing operator authentication contract rather than introduce a new user-visible authentication flow.
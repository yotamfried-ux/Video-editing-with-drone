# Multipart upload foundation — official implementation basis

Date: 2026-07-22  
Gaps: GAP-013, GAP-014 decision, GAP-015, GAP-026  
Status: implementation foundation in progress; no end-to-end closure claim

## Verified root cause

The production operator path currently requests one signed `PUT` URL and sends the complete video through Expo `createUploadTask`. A retry requests another URL and retransmits the complete file. The batch identifier is held partly in React state, and the server does not have an authoritative intended-file manifest that must be `verified` before dispatch.

For SD/USB, the current app copies every selected `content://` source into app cache before the same complete-file upload. That is not acceptable for large 4K footage and does not provide durable process-restart recovery.

The current production upload path also has no exact-content duplicate protection. Every upload receives a new timestamped R2 key, and post-upload verification checks existence and size rather than a stable content digest. Two byte-identical videos can therefore both remain eligible for processing.

The multipart foundation branch introduces a client-supplied `source_fingerprint` and an active-state partial unique index, but that is not sufficient for the required behavior: the fingerprint algorithm and trust boundary are unspecified, the index excludes `verified` rows, and there is no atomic newest-verified-wins transition or safe superseded-object cleanup.

## Official source code used as the implementation basis

### Cloudflare R2

Official documentation source:

- `cloudflare/cloudflare-docs`, `workers-multipart-usage.mdx`:
  https://github.com/cloudflare/cloudflare-docs/blob/6f6b2965eabc9665cd15ba9f567d11645fe9e81d/src/content/docs/r2/api/workers/workers-multipart-usage.mdx
- R2 upload limits and multipart guidance:
  https://github.com/cloudflare/cloudflare-docs/blob/6f6b2965eabc9665cd15ba9f567d11645fe9e81d/src/content/docs/r2/objects/upload-objects.mdx

Adopted structure:

1. Create returns a durable upload identifier and canonical object key.
2. Each part request is scoped to the same upload and part number.
3. The exact returned part number and ETag are retained outside the stateless request.
4. Complete receives the complete part ledger.
5. Abort is explicit.
6. Authentication, validation, durable state, and business admission are added around the provider example rather than trusting the client.

### AWS SDK for JavaScript v3

Official implementation source:

- `aws/aws-sdk-js-v3`, `lib-storage/src/Upload.ts`:
  https://github.com/aws/aws-sdk-js-v3/blob/80f0df5b1971a205f172b880ea3fc8c4e9b8aacf/lib/lib-storage/src/Upload.ts

Adopted invariants:

- minimum part size: 5 MiB;
- maximum part count: 10,000;
- part size expands automatically when needed to remain under the part-count limit;
- every upload-part response must include an ETag;
- uploaded part count must equal the expected count;
- parts are sorted by `PartNumber` before complete;
- all active upload workers settle before abort, so an abort cannot race with an upload and leave stranded parts;
- mobile concurrency will start below the library's server-oriented default of four and will be measured on a physical phone.

The project does not copy `Upload.ts`. It mirrors its provider invariants in a small dependency-free policy module and uses the existing R2 SigV4 boundary to issue short-lived, part-scoped S3-compatible URLs. This avoids exposing R2 credentials and avoids introducing a second signing implementation in the mobile app.

### Expo SDK 52 and Android content URIs

Official SDK 52 source:

- File API and `FileHandle` declarations:
  https://github.com/expo/expo/blob/sdk-52/packages/expo-file-system/src/next/ExpoFileSystem.types.ts
- SDK 52 Android implementation:
  https://github.com/expo/expo/blob/sdk-52/packages/expo-file-system/android/src/main/java/expo/modules/filesystem/next/FileSystemNextModule.kt
- SDK 52 `FileBlob.slice()` implementation:
  https://github.com/expo/expo/blob/sdk-52/packages/expo-file-system/src/next/FileSystem.ts

Verified findings:

- SDK 52 exposes `open()`, `readBytes(length)`, mutable `offset`, and `close()` under `expo-file-system/next`.
- `FileBlob.slice()` calls `this.file.bytes().slice(...)`, so it materializes the complete file before slicing and is forbidden for large source video.
- The SDK 52 Android native constructor converts the URI path into `java.io.File`; it does not open `content://` through Android `ContentResolver`. Therefore its random-access handle is not sufficient evidence for SD/USB SAF sources.

Newer official Expo Android source has a `ContentResolver`/SAF-backed file handle path:

https://github.com/expo/expo/blob/main/packages/expo-file-system/android/src/main/java/expo/modules/filesystem/FileSystemFile.kt

Decision for GAP-014:

- Do not hide the SDK 52 limitation by copying the complete external video to cache.
- Do not use `bytes()`, `bytesSync()`, base64, or `FileBlob.slice()`.
- Implement GAP-014 in a dedicated controlled Expo/native upgrade PR targeting a released Expo version whose installed Android source supports `ContentResolver`/SAF random-access handles.
- Prove support with an EAS native build and a physical SD/USB test before replacing the current external-source path.

### Exact-content identity and newest-verified replacement

Official documentation and reference implementations:

- Cloudflare R2 Workers API exposes stored object checksums, custom metadata, upload-time SHA-256 validation for supported writes, and conditional operations:
  https://developers.cloudflare.com/r2/api/workers/workers-api-reference/
- Cloudflare documents that multipart ETags are derived from part MD5 values and are not a portable full-file content identity:
  https://developers.cloudflare.com/r2/objects/upload-objects/
- AWS documents explicit object checksums, multipart checksum behavior, and that a multipart ETag is not the MD5 digest of the complete object:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html
- AWS's official sample repository demonstrates multipart SHA-256 calculation and comparison:
  https://github.com/aws-samples/amazon-s3-checksum-tool
- Dropbox's official content-hash contract demonstrates comparing a locally computed content hash with the server copy to prove exact equality:
  https://www.dropbox.com/developers/reference/content-hash
- GitHub Git LFS identifies large-file content with a versioned `sha256` OID plus exact size:
  https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage
- The official `git-lfs/git-lfs` specification and implementation use SHA-256 content identity and an atomic move only after the content matches the expected OID:
  https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md
- PostgreSQL documents partial unique indexes for enforcing one qualifying canonical row and atomic `INSERT ... ON CONFLICT` behavior under concurrency:
  https://www.postgresql.org/docs/current/indexes-partial.html
  https://www.postgresql.org/docs/current/sql-insert.html

Adopted conclusions for SportReel:

1. Filename, client upload ID, R2 key, upload timestamp, and multipart ETag are not exact-content identity.
2. Exact duplicate detection must use a versioned cryptographic content digest, with SHA-256 as the initial application identity algorithm.
3. The digest must be computed incrementally while bounded parts are read; hashing must not materialize the complete 4K file in memory or require an additional whole-file cache copy.
4. For multipart objects, provider checksum semantics must be recorded explicitly. A composite checksum may be used only when algorithm, deterministic part boundaries, checksum type, and version are encoded; it must never be mislabeled as a full-file SHA-256.
5. A client-provided digest alone is not sufficient closure evidence. The system must bind it to verified size and provider-validated part/object integrity, and must perform a trusted read-back or equivalent deterministic verification before destructive cleanup.
6. Deduplication applies globally to exact source content, not merely to matching filenames or one batch.
7. The newest successfully verified upload wins according to durable server `verified_at`, never device clock, filename, or request arrival alone.
8. Older metadata is retained for audit lineage as `superseded`; only the newer canonical source remains eligible for future pipeline admission.
9. Old R2 bytes are deleted only after the new canonical object is verified, the canonical database transition commits, active references are repointed or proven safe, and deletion can be retried idempotently.
10. A failed new upload must not supersede or delete the previously verified canonical source.

## Foundation architecture

### Durable database authority

A tracked Supabase migration introduces:

- `upload_batches`: expected membership, grouping semantics, roll-up counts, and readiness/dispatch state;
- `upload_files`: client idempotency key, immutable R2 key, R2 upload ID, source identity/size, part policy, uploaded bytes, verification, and terminal state;
- `upload_parts`: exact part number, ETag, size, retry count, and completion time.

RLS is enabled and no anon/authenticated policies are created. The operator web API uses the service role; the mobile client is never database authority.

### Multipart API state machine

The authenticated operator API supports:

- `create_batch`;
- idempotent `create_upload`;
- short-lived `part_url`;
- idempotent `record_part` with exact size/ETag;
- `complete` only after database and R2 `ListParts` reconciliation;
- `DELETE` abort only after the client reports no in-flight part requests;
- GET restoration by `client_upload_id` or `batch_id`.

Completion requires:

1. the complete durable part ledger;
2. exact part sizing;
3. exact ETag equality with R2 `ListParts`;
4. ascending part order;
5. successful R2 complete;
6. `HEAD Content-Length === source_size_bytes`;
7. only then `state='verified'`.

The multipart final ETag is retained as provider metadata and is never treated as source-file MD5.

### Exact duplicate canonicalization contract

GAP-026 requires the upload schema and API to add:

- `content_digest_algorithm`, `content_digest_version`, and `content_digest` fields that cannot be changed after verification;
- `verified_at`, `canonicalized_at`, `superseded_at`, `superseded_by_upload_file_id`, and cleanup state/error fields;
- a state distinction between transport-complete, integrity-verified, canonical, superseded, and cleanup-failed;
- one database transaction/RPC that locks the competing digest rows, confirms the new row is fully verified, promotes the newest row, and supersedes the prior canonical row;
- a partial unique index ensuring at most one canonical row for one `(digest_algorithm, digest_version, content_digest, source_size_bytes)` identity;
- deterministic batch roll-up adjustment so superseded duplicates do not inflate expected/verified membership or make the pipeline process the same bytes twice;
- an immutable audit event recording old/new upload IDs, old/new R2 keys, digest identity, timestamps, decision reason `exact_content_duplicate`, and cleanup result;
- idempotent R2 deletion or lifecycle cleanup after reference-safety verification;
- pipeline admission that resolves only canonical source rows and rejects unresolved duplicate/canonicalization states.

The existing active-only `source_fingerprint` unique index is a temporary conflict guard, not GAP-026 closure. It must not be represented as exact-content deduplication.

### Pipeline admission

For R2 runs, `POST /api/operator/pipeline/start` requires an authoritative batch. The server checks:

- batch state is `ready`;
- durable file count equals expected count;
- verified count equals expected count;
- every file is `verified`;
- every verified size equals its source size.

It then conditionally claims `ready → dispatching`. Only one request can win. Dispatch failure releases the claim to `ready`; accepted dispatch becomes `dispatched`. The exact immutable object manifest is written into `pipeline_runs.input_files` before repository dispatch.

Before GAP-026 can close, admission must additionally prove that every selected source resolves to the current canonical digest row and that no two input manifest entries share the same exact-content identity.

## Tests required in this PR

- executable Node contract for part sizing, 10,000-part limit, last-part sizing, ETag preservation, duplicate rejection, exact byte totals, and ascending completion order;
- source contract covering migration/RLS, API actions, R2 create/list/complete/abort calls, HEAD equality, and batch claim/release;
- web-api TypeScript;
- existing operator/pipeline contracts affected by upload and dispatch;
- negative cases for incomplete ledger, wrong part size, missing ETag, reused idempotency key, unready batch, concurrent batch claim, dispatch timeout, and dispatch rejection;
- GAP-026 contract tests proving byte-identical uploads with different filenames/batches resolve to one canonical row, the newer verified upload wins, concurrent completion cannot create two canonical rows, a failed replacement preserves the old canonical row, multipart ETag is rejected as content identity, cleanup failure remains visible/retryable, and pipeline manifests contain no duplicate content digest.

## Explicitly deferred from this foundation PR

The following remain unchecked in `docs/app-pipeline-audit.md` until real evidence exists:

- applying and verifying the migration in the live Supabase project;
- mobile bounded part reads and incremental SHA-256 computation;
- persisted Android upload restoration;
- persistable URI permission and source reconnection;
- physical Android memory/network/restart/SD/USB tests;
- real R2 multipart reconstruction and network interruption;
- trusted exact-content digest verification against completed R2 objects;
- a real duplicate upload with different names and/or batches proving newest-verified retention, old-object cleanup, and preserved lineage;
- real 2–3 video batch run;
- production deployment evidence.

No foundation code or green CI result closes GAP-013, GAP-014, GAP-015, or GAP-026 by itself.

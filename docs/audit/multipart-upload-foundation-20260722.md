# Multipart upload foundation — official implementation basis

Date: 2026-07-22  
Gaps: GAP-013, GAP-014 decision, GAP-015  
Status: implementation foundation in progress; no end-to-end closure claim

## Verified root cause

The production operator path currently requests one signed `PUT` URL and sends the complete video through Expo `createUploadTask`. A retry requests another URL and retransmits the complete file. The batch identifier is held partly in React state, and the server does not have an authoritative intended-file manifest that must be `verified` before dispatch.

For SD/USB, the current app copies every selected `content://` source into app cache before the same complete-file upload. That is not acceptable for large 4K footage and does not provide durable process-restart recovery.

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

### Pipeline admission

For R2 runs, `POST /api/operator/pipeline/start` requires an authoritative batch. The server checks:

- batch state is `ready`;
- durable file count equals expected count;
- verified count equals expected count;
- every file is `verified`;
- every verified size equals its source size.

It then conditionally claims `ready → dispatching`. Only one request can win. Dispatch failure releases the claim to `ready`; accepted dispatch becomes `dispatched`. The exact immutable object manifest is written into `pipeline_runs.input_files` before repository dispatch.

## Tests required in this PR

- executable Node contract for part sizing, 10,000-part limit, last-part sizing, ETag preservation, duplicate rejection, exact byte totals, and ascending completion order;
- source contract covering migration/RLS, API actions, R2 create/list/complete/abort calls, HEAD equality, and batch claim/release;
- web-api TypeScript;
- existing operator/pipeline contracts affected by upload and dispatch;
- negative cases for incomplete ledger, wrong part size, missing ETag, reused idempotency key, duplicate source fingerprint, unready batch, concurrent batch claim, dispatch timeout, and dispatch rejection.

## Explicitly deferred from this foundation PR

The following remain unchecked in `docs/app-pipeline-audit.md` until real evidence exists:

- applying and verifying the migration in the live Supabase project;
- mobile bounded part reads;
- persisted Android upload restoration;
- persistable URI permission and source reconnection;
- physical Android memory/network/restart/SD/USB tests;
- real R2 multipart reconstruction and network interruption;
- real 2–3 video batch run;
- production deployment evidence.

No foundation code or green CI result closes GAP-013, GAP-014, or GAP-015 by itself.

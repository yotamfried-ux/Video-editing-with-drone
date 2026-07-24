# Drone large-upload experiment-entry plan

Date: 2026-07-23  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Scope: GAP-013, GAP-014, the upload portion of GAP-015, and the production evidence needed before the first real drone-footage experiment.

## Outcome

The operator must be able to select large 4K drone videos directly from Android SD/USB storage, upload them to Cloudflare R2 without first copying the complete file into phone storage, survive transient network/app interruptions, and start the pipeline only after every intended source is durably size-verified.

This work is an experiment-entry prerequisite. It does not claim that perception, identity, editing quality, QA, delivery, or the full product vision are complete.

## Non-negotiable source and phone-storage safety rules

1. The application must never delete, rename, move, or overwrite the original `content://` source selected from SD/USB.
2. App-owned temporary files must use a dedicated SportReel cache prefix and must never share a path with the original source.
3. A completed upload is not successful until R2 `HEAD Content-Length` equals the durable `source_size_bytes` and the source row reaches `verified`.
4. Immediately after durable verification, every app-owned temporary file associated with that source must be deleted idempotently and the cleanup result recorded.
5. Cleanup must verify absence after deletion. A failed cleanup is visible as `cleanup_failed`; it must not silently consume storage.
6. Startup recovery must sweep abandoned app-owned upload cache files that are not attached to an active durable upload. It must not sweep arbitrary cache files.
7. Failed/paused uploads may discard disposable part buffers, but must retain the durable multipart upload ID, exact completed-part ledger, source identity, and next missing part.
8. The steady-state multipart path must use in-memory bounded part buffers or another bounded app-owned artifact. It must not require a complete local copy of a drone video.
9. When the source provider cannot support safe seeking/resume, the app must report `source_not_seekable` and require a safer source/provider; it must not fall back silently to a whole-file cache copy.
10. A multipart part is not durable until the exact R2 response `ETag`, part number, and byte count have been recorded. Missing or unreadable `ETag` is an upload failure, not a reason to invent or calculate a replacement value.

## Documentation and implementation evidence checked

### Cloudflare R2

Authoritative current sources:

- https://developers.cloudflare.com/r2/objects/upload-objects/
- https://developers.cloudflare.com/r2/api/s3/api/
- https://developers.cloudflare.com/r2/api/error-codes/
- https://developers.cloudflare.com/r2/buckets/cors/
- https://developers.cloudflare.com/r2/platform/limits/

Verified constraints used by the implementation:

- Multipart is the recommended path for video, large files, resumability, and parallelism.
- Each non-final part must be 5 MiB to 5 GiB and all non-final parts must be the same size.
- A multipart object supports at most 10,000 parts and approximately 5 TiB.
- Completion must use the exact returned part ETags and ascending part numbers.
- A failed part can be retried independently.
- Incomplete multipart uploads are aborted by R2 after seven days by default, but SportReel still needs an explicit application cleanup/abort policy.
- The final multipart ETag is not a source-file MD5 and must not be used as one.
- JavaScript can read `ETag` only when the runtime exposes that response header. Cloudflare documents `ExposeHeaders: ["ETag"]` for browser CORS policies. The installed Android native runtime may behave differently from a browser, so the exact production bucket/build combination must be tested rather than inferred.

### Expo SDK 52 compatibility decision

The installed app is pinned to Expo `~52.0.28` and `expo-file-system ~18.0.10`.

The exact Expo `sdk-52` source was inspected rather than assuming current documentation applies:

- `packages/expo-file-system/src/next/ExpoFileSystem.types.ts` exposes `FileHandle.readBytes`, `offset`, `size`, and `close`.
- The Android `sdk-52` implementation constructs that API from `java.io.File(uri.path)`. It therefore does not provide a safe `content://` SD/USB random-access reader.
- The legacy SDK 52 `readAsStringAsync` supports `position` and `length` for Base64 reads, including SAF URIs, but reopens the stream and skips from the beginning for every call. It is not accepted as the durable large-video implementation because it adds Base64 memory overhead and does not guarantee efficient random access.
- The Expo SDK 55 Android source was also checked. It adds general SAF adapters, but its `FileHandle` still opens `RandomAccessFile(file.javaFile, "rw")`, while `javaFile` explicitly rejects content URIs. A broad Expo upgrade alone therefore does not prove the required SD/USB behavior.

Decision: retain the current Expo SDK during the upload foundation and add a focused Android Expo local module for bounded range reads from a selected content URI. Any later Expo upgrade remains a separate compatibility PR.

### Android

Authoritative sources:

- https://developer.android.com/training/data-storage/shared/documents-files
- https://developer.android.com/reference/android/content/ContentResolver#openFileDescriptor(android.net.Uri,%20java.lang.String)
- https://developer.android.com/reference/android/content/Intent#FLAG_GRANT_PERSISTABLE_URI_PERMISSION

Implementation direction:

- Use the Storage Access Framework for user-selected SD/USB sources.
- Persist read permission where the provider grants it.
- Open the selected URI with `ContentResolver` and a native file descriptor.
- Read no more than the configured part size from an explicit byte offset.
- Detect a non-seekable provider instead of copying the entire source locally. Android explicitly permits a read descriptor to be backed by a pipe/socket, so seekability must be tested on the exact provider.
- Close every descriptor/channel in `finally`/scoped resource cleanup.

### Expo local module

Authoritative sources:

- https://docs.expo.dev/modules/get-started/
- https://docs.expo.dev/modules/module-api/
- https://docs.expo.dev/more/create-expo-module/
- https://docs.expo.dev/develop/development-builds/expo-go-to-dev-build/

The Expo Modules API maps Kotlin `ByteArray` to JavaScript `Uint8Array` on SDK 50+, which permits a bounded binary part to cross the native boundary without Base64. A production/development native build is required; Expo Go is not sufficient for this custom module.

## Implementation sequence

### Phase A — durable R2 multipart server foundation

- [ ] Add tracked Supabase schema for multipart upload metadata, idempotent start, exactly-once batch membership, and exact part ETags.
- [ ] Create multipart, part-URL, part-record, complete, reconcile, abort, and cleanup-confirmation endpoints.
- [ ] Enforce part size/count limits and short-lived part URLs.
- [ ] On completion, compare durable source size with R2 `HEAD Content-Length` before `verified`.
- [ ] Prove the exact Android runtime can read the R2 part `ETag`; if CORS applies, deploy and verify an R2 policy that exposes `ETag` without broadening origins unnecessarily.
- [ ] Make abort and stale-upload cleanup explicit in addition to R2's lifecycle.

### Phase B — bounded Android SD/USB reader

- [ ] Add a focused Android Expo local module.
- [ ] Return at most one configured part as `Uint8Array` from an explicit offset.
- [ ] Persist URI permission where supported.
- [ ] Detect unavailable, changed, removed, and non-seekable sources.
- [ ] Close descriptors/channels in all paths.

### Phase C — durable mobile upload ledger and local cleanup

- [ ] Persist source URI identity, source size/fingerprint, idempotent start ID, server upload ID, part size, completed ETags, retry state, and next missing part.
- [ ] Restore the same upload after process death/restart.
- [ ] Retry only the missing/failed part.
- [ ] Remove each in-memory/temporary part artifact after its request settles.
- [ ] After server verification, delete all app-owned temporary files for the source, verify absence, and report `confirmed`/`failed` durably.
- [ ] Sweep only stale SportReel-owned upload artifacts at startup.
- [ ] Never delete the SD/USB source.

### Phase D — verified batch gate

- [ ] Restore unfinished batch membership after restart without incrementing expected membership twice.
- [ ] Calculate readiness on the server from durable rows.
- [ ] Disable/reject pipeline start while any intended source is not size-matched `verified` or its required local cleanup is unresolved.
- [ ] Freeze and record the exact R2 input list before analysis.

### Phase E — real evidence gate

- [ ] Apply migrations in dependency order and verify the live Supabase schema/RPCs.
- [ ] Verify the production R2 bucket exposes the exact part `ETag` to the installed Android build.
- [ ] Install the exact EAS/native build on the target Android device.
- [ ] Upload a representative 4K drone video from SD/USB.
- [ ] Prove phone storage does not grow by the full source size.
- [ ] Interrupt the network and prove only the missing part is resent.
- [ ] Lose the multipart-start response and prove retry resolves the same `client_upload_id`, source row, R2 upload, and batch membership.
- [ ] Force-close/restart and resume the same upload.
- [ ] Remove/reconnect the SD card and recover truthfully.
- [ ] Verify final R2 size, durable part ledger, local cleanup confirmation, reclaimed-byte evidence, and absence of SportReel temporary upload files.
- [ ] Upload a 2–3 video batch and prove every intended source enters one run exactly once.

## Closure rule

GAP-013/014 are not closed by code review or CI alone. They become experiment-entry ready only after the exact deployed API, migration, R2 bucket/CORS behavior where applicable, native build, Android device, SD/USB provider, and real large video pass the evidence gate above.

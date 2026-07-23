#!/usr/bin/env python3
"""One-shot reconciliation of the authoritative upload readiness audit."""

from pathlib import Path

PATH = Path("docs/app-pipeline-audit.md")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    source = PATH.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "Baseline inspected: `main` at merge commit `c23b819866306980f8ebe454958bf7802d0145a4` (PR #193)  ",
        "Baseline validated for this update: `main` at `f0ce8d742110a2101dd86fa37a07d54409b01bc2` (merged PR #195), plus the implementation under review in PR #196. Live release evidence remains pending until PR #196 is merged.  ",
        "audit baseline",
    )

    source = replace_once(
        source,
        "- Upload currently uses one signed `PUT` per complete file, followed by server-side `HEAD` verification.\n- Gallery uploads can run concurrently; SD/USB uploads are copied one complete file at a time into app cache before the same full-file upload.",
        "- Gallery uploads retain the signed single-`PUT` path, now with an explicit source-size evidence field and server-side `HEAD` verification.\n- PR #196 replaces the Android SD/USB path with bounded `content://` range reads and durable R2 multipart upload; it does not create a complete phone-cache copy.",
        "current upload baseline",
    )

    source = replace_once(
        source,
        "- Structured operator feedback exists, but the real feedback-to-database-to-next-run learning loop is not production-validated.",
        "- Structured operator feedback exists, but the real feedback-to-database-to-next-run learning loop is not production-validated.\n- PR #195 is merged and provides durable source manifests plus exact byte-duplicate reconciliation.\n- PR #196 implements multipart resume, exact part ETags, local cleanup evidence, idempotent start, durable batch readiness, Android native compilation, and a fail-closed release workflow. These are foundation-level claims until the live migration/R2/build jobs pass after merge.",
        "upload foundation baseline evidence",
    )

    source = replace_once(
        source,
        "| GAP-013 — Resumable multipart R2 upload | P0 | Single full-file PUT; retry restarts the file | Yes |",
        "| GAP-013 — Resumable multipart R2 upload | P0 | Foundation implemented in PR #196; live R2 and interruption evidence pending | Yes, until release/device evidence passes |",
        "GAP-013 summary",
    )
    source = replace_once(
        source,
        "| GAP-014 — Durable Android source access and restart recovery | P0 | SD/USB file is copied in full to cache; upload state is not durable | Yes |",
        "| GAP-014 — Durable Android source access and restart recovery | P0 | Native bounded reader and durable ledger implemented; installed-device restart/storage evidence pending | Yes, until APK/device evidence passes |",
        "GAP-014 summary",
    )
    source = replace_once(
        source,
        "| GAP-015 — Durable batch/session/athlete upload manifest and verified-run gate | P0 | Exact-content upload dedup foundation exists in this PR; durable batch readiness and grouping remain incomplete | Yes |",
        "| GAP-015 — Durable batch and verified-run gate | P0 | Source/batch manifests and admission gate implemented; athlete/session business grouping and real batch proof remain open | Yes for full experiment grouping |",
        "GAP-015 summary",
    )

    source = replace_once(
        source,
        "- `web-api/src/lib/r2-storage.ts` creates a single signed `PUT` URL.\n- `mobile/src/app/(operator)/pipeline.tsx` uploads the whole file with `createUploadTask`.\n- Automatic retry requests a new upload session and resends the whole file.\n- `POST /api/operator/upload/verify` verifies object existence, but the current mobile request does not provide the original source size as a required equality check.\n- Large 4K video can therefore lose all progress after a network interruption.",
        "- PR #196 adds R2 create/upload-part/complete/abort operations and short-lived part URLs.\n- The Android client reads one bounded range at a time, stores exact part ETags durably, reconciles against server state, and skips already recorded parts after restart.\n- Completion is sorted by part number and becomes `verified` only after R2 `HEAD Content-Length` equals the durable source size.\n- The final multipart ETag is explicitly not treated as a source MD5.\n- A failed cleanup remains visible and prevents the batch from becoming ready.\n- `.github/workflows/upload-foundation-release.yml` applies migrations, runs a real R2 multipart/hash/cleanup probe, and only then builds the Android preview APK.\n- Real R2, network interruption, and installed-device evidence remain pending until the post-merge release run.",
        "GAP-013 verified state",
    )

    for old in [
        "- [ ] A tracked Supabase migration creates the durable multipart upload schema.",
        "- [ ] The web-api creates multipart uploads through the official R2 S3-compatible API and returns `upload_id`, canonical `r2_key`, `part_size_bytes`, and protocol version.",
        "- [ ] The server issues short-lived signed URLs scoped to one `upload_id` and `part_number`.",
        "- [ ] Every non-final part is the configured uniform size and at least 5 MiB.",
        "- [ ] The total part count cannot exceed 10,000.",
        "- [ ] The client stores the exact returned `ETag` and `part_number` for every completed part.",
        "- [ ] Completion sends all parts sorted by ascending `PartNumber`.",
        "- [ ] A failed part is retried without retransmitting successful parts.",
        "- [ ] `HEAD Content-Length` equals `source_size_bytes` before the upload becomes `verified`.",
        "- [ ] Multipart final ETag is not incorrectly treated as the source-file MD5.",
        "- [ ] A deterministic contract test covers part sizing, ordering, exact ETags, single-part retry, complete, abort, and size mismatch.",
    ]:
        source = replace_once(source, old, old.replace("- [ ]", "- [x]"), f"check {old}")

    source = replace_once(
        source,
        "- The installed code uses Expo SDK 52 and legacy `FileSystem.copyAsync`/`createUploadTask`.\n- SD/USB `content://` sources are copied in full into app cache before upload.\n- Upload state is held in React component state, so process death or app restart cannot reliably resume.\n- The physical retest proving only selected external videos are uploaded remains open.",
        "- The app remains on Expo SDK 52; a focused Expo local Android module was chosen instead of assuming newer `FileHandle` behavior applies.\n- The module uses `ContentResolver`, seekable file descriptors, explicit offsets, and a 64 MiB hard ceiling; the upload part size defaults to 16 MiB.\n- The normal SD/USB path contains no whole-file `copyAsync`, Base64 fallback, or file-sized cache artifact.\n- AsyncStorage and Supabase preserve upload identity, completed parts, ETags, retry state, and batch membership.\n- Expo SDK 52's official `requestDirectoryPermissionsAsync` implementation persists the granted tree URI permission.\n- App-owned temporary artifacts are deleted only after exact R2 verification; absence and reclaimed bytes are recorded, while the original `content://` source is preserved.\n- Native prebuild, autolinking, TypeScript, and `:app:compileDebugKotlin` pass in CI. Physical SD/USB, force-close, memory, and storage measurements remain open.",
        "GAP-014 verified state",
    )

    for old in [
        "- [ ] An explicit compatibility decision is recorded: either prove `FileHandle` behavior on Expo 52 or upgrade Expo through a dedicated, tested PR.",
        "- [ ] Large source files are read in bounded parts using an official random-access/stream API rather than `bytes()`, `bytesSync()`, base64, or a whole-file cache copy.",
        "- [ ] The file handle offset is set deterministically for each part.",
        "- [ ] Each read returns at most the configured part size.",
        "- [ ] Every handle is closed in `finally` on success, retry, pause, cancellation, and error.",
        "- [ ] Durable state survives app restart and restores the same source, upload ID, completed-part ledger, and next missing part.",
        "- [ ] Android persistable URI permission is requested/stored where the source provider supports it.",
        "- [ ] If the SD/USB device is removed, state becomes `source_unavailable` without aborting or losing completed parts.",
        "- [ ] Reconnecting the same source resumes; selecting a different file with the same name is rejected by fingerprint/size checks.",
        "- [ ] Temporary files, if any are still needed for a limited compatibility fallback, are bounded, documented, and removed in `finally`.",
    ]:
        source = replace_once(source, old, old.replace("- [ ]", "- [x]"), f"check {old}")

    source = replace_once(
        source,
        "- `activeBatchId` lives in mobile component state and can be lost.\n- A batch does not yet have a durable authoritative manifest describing intended files, source sizes, upload states, session purpose, or athlete grouping.\n- `batch_id` is a transport boundary, but it is not yet a complete `session_id`/`athlete_id` business grouping contract.\n- Pipeline start can be requested without a server-side proof that all intended files are verified.",
        "- `upload_batches` records intended, registered, verified, and cleanup-pending counts and freezes the exact input manifest before dispatch.\n- AsyncStorage restores an unfinished multipart source; the API can recover a unique active or ready batch from Supabase instead of trusting React state.\n- `client_upload_id` makes multipart start and batch membership idempotent after a lost response or concurrent retry.\n- Pipeline start is rejected before creating a run unless every intended source is size-matched `verified` and required local cleanup is confirmed.\n- Gallery uploads now send a client file size where available; the legacy fallback records weaker evidence as `r2_head_adopted` instead of pretending it was client-declared.\n- `batch_id` still lacks the complete `session_id`/explicit athlete/operator business-grouping contract required for the final product. Live migration and real 2–3 file batch evidence remain pending.",
        "GAP-015 verified state",
    )

    for old in [
        "- [ ] Each selected source has one durable upload record containing the fields required by GAP-013/014.",
        "- [ ] RLS is enabled for exposed tables; service-role writes remain server-side only.",
        "- [ ] The app restores an unfinished batch after restart instead of silently creating a new one.",
        "- [ ] Adding more files to the same batch is explicit and preserves existing verified membership.",
        "- [ ] Filename reuse cannot overwrite or impersonate another source; canonical R2 keys remain immutable.",
        "- [ ] Two byte-identical verified uploads must resolve to one canonical source. The newest verified upload is retained, the older source is marked superseded and removed from pipeline eligibility, and the decision is recorded with SHA-256 evidence and reason `exact_content_duplicate`.",
        "- [ ] Canonical choice is based on the first successful `verified_at`, never filename, R2 key order, client clock, or a repeated verification request.",
        "- [ ] The older R2 object is deleted only after the newer object is fully verified; deletion failure remains visible and the old source remains ineligible.",
        "- [ ] Re-exported or perceptually similar video is not auto-deleted by the exact-content SHA-256 rule.",
        "- [ ] The server calculates batch readiness from durable rows, not mobile state.",
        "- [ ] `Run pipeline now` is rejected with an actionable response unless all intended files are `verified` and size-matched.",
        "- [ ] The dispatch payload contains the authoritative `batch_id` and `pipeline_run_id`.",
        "- [ ] The workflow lists only `raw/<batch_id>/` and records the exact input object list before processing.",
    ]:
        source = replace_once(source, old, old.replace("- [ ]", "- [x]"), f"check {old}")

    evidence = """

### Upload-foundation implementation evidence — 2026-07-23

- Merged foundation: PR #195, merge commit `f0ce8d742110a2101dd86fa37a07d54409b01bc2`.
- Implementation under review: PR #196 (`Build reliable large drone-video upload foundation`).
- Deterministic evidence includes External Storage Upload Check, Large Upload Foundation Check, Mobile Check, Operator Smoke Check, exact-source dedup checks, Expo autolinking, Android prebuild, and Kotlin compilation.
- Official implementation bases are Cloudflare R2 multipart/S3 compatibility, Android Storage Access Framework and `ContentResolver`, Expo SDK 52 source plus Expo Modules API, Supabase migrations/RLS, and Expo's official GitHub Action/EAS CLI.
- Release is fail-closed: migrations and schema verification must pass, then the real R2 probe must upload/retry/hash-check/delete successfully, and only then may the Android preview APK be built.
- This section proves **foundation implemented**, not **experiment entry ready**. The live release run, Vercel production commit, installed APK, phone-storage measurement, interruption/restart test, and real footage remain mandatory evidence.
"""
    marker = "\n## 5. Entry gate for the next production-style experiment\n"
    if evidence.strip() not in source:
        source = replace_once(source, marker, evidence + marker, "implementation evidence insertion")

    PATH.write_text(source, encoding="utf-8")
    print("Authoritative upload audit reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

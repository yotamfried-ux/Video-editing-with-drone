# Annotation Studio — M0 repository investigation, gap analysis and plan

Date: 2026-10-30. Spec: [`docs/specs/ground-truth-annotation-studio.md`](../specs/ground-truth-annotation-studio.md).
Scope of this document: read-only investigation. No production resource was touched.

## 1. What exists and what is reusable

| Area | Evidence in repo | Reusable? |
|---|---|---|
| Upload to R2 with exact-content dedup | `supabase/migrations/20260723_source_upload_*.sql` (`source_uploads`: `storage_key`, `content_sha256`, `status`, `canonical_upload_id`, `source_upload_dedup_audit`), `web-api/src/lib/source-upload-manifest.ts`, `multipart-upload-manifest.ts` | **Concept yes, table no.** `source_uploads` is keyed to `storage_key` and its dedup *supersedes and removes* the older object. That is the opposite of a permanent identity. Studio reads it only as an optional discovery feed (`SourceFeed`), never writes to it. |
| Storage lifecycle | `web-api/src/lib/video-storage-cleanup.ts`: deletes videos under `raw/ processed/ review/ approved/ pending_payment/ pending_uploads/ previews/` and Supabase `reels`; `metadata/` protected | Confirms spec §3: operational prefixes are deletable. Studio archive must live outside these prefixes **and outside this bucket/credential**. |
| Operator auth | `web-api/src/lib/operator-auth.ts` (`x-operator-secret`), `OPERATOR_SECRET` | **Not reused.** Pipeline/API hold this and the Supabase service key. Studio uses its own token so pipeline credentials never reach Ground Truth. |
| Pipeline detection/tracking | `pipeline/perception/{schema,crop_math,producer,track_stitching}.py` (bbox xyxy per frame, tracker_id) | Reusable as **prediction input format** for M4 (read-only from run artifacts). Not imported by Studio. |
| Framing decision | `pipeline/quality_preserving_framing.py` `decide_framing` -> `mode` `contain`/crop, reason strings | Provides per-event mode, **not** a per-frame EDL. |
| Rendered timeline | `pipeline/rendered_timeline.py` (`rendered_timeline_start/end` per event) | Event-level output->source offsets only. |
| CI conventions | `.github/workflows/*` path-filtered, narrow per-contract workflows; `web-api-auth-boundary.yml` | Follow the pattern: add `annotation-studio-check.yml`, path-filtered to `annotation-studio/**`. |
| Existing GT design docs | `docs/ground-truth-annotation-system-design.md`, addendum, guidelines (mobile-first, Postgres) | Superseded in *delivery form* by the studio spec (desktop, local). Reused: blind-evaluation contract, event-scoped ownership, immutable revisions, annotation-set isolation (future multi-annotator). |

## 2. Gaps (spec requirement -> status)

| # | Gap | Severity | Plan |
|---|---|---|---|
| G1 | No stable source identity independent of path | P0 | `sources` (UUID) + `sha256,byte_size` unique + many `source_locations` (M2) |
| G2 | No protected archive; cleanup service can delete all originals | P0 | `ArchiveStore` interface; local protected-root implementation now; R2 adapter **blocked on approval** (new bucket = new resource) |
| G3 | No annotation store / revisions | P0 | Isolated SQLite DB, append-only revision tables enforced by triggers (M3) |
| G4 | **Pipeline emits no per-frame EDL** (only event-level mode + rendered offsets) | P0 for M5 | Studio defines `edl/v1` schema + validator + transform math and marks any run without one `unverified_mapping`. Emitting EDL from the pipeline is a production-pipeline change -> needs separate approval; not done here. |
| G5 | No evaluation service / frozen datasets | P1 | M4 deterministic matcher, dataset freeze with manifest digest |
| G6 | No Studio UI | P1 | M1 |
| G7 | Real R2/Supabase isolation (separate bucket, DB project, credentials) | P0 for production | Cannot be created without approval/paid resources; designed behind adapters, tested with local fixtures. **Not claimed as production integration.** |
| G8 | Playback proxy / thumbnails | P2 | ffmpeg (available) generates thumbnail + 720p proxy at ingest |

## 3. Architecture decision (recorded; reversible defaults)

* New top-level `annotation-studio/`. **Zero npm dependencies**: Node 22 `node:sqlite` + built-in `http`; vanilla ES-module front-end. Rationale: no supply-chain or paid surface, fully local, nothing shared with `web-api/` (Vercel-deployed, holds service keys).
* Binds `127.0.0.1` only. Every `/api` call needs a per-install random token (bearer or HttpOnly cookie set by a one-time launch URL). Secrets are never in client bundles.
* Own state dir (`STUDIO_HOME`): `studio.sqlite`, `archive/` (content-addressed, files chmod 0444, write-once), `cache/` (thumbs/proxies; disposable).
* Isolation proof tests: no file outside `annotation-studio/` references it; no pipeline/web-api path reads `STUDIO_*`; API rejects missing/invalid token.
* Frames are canonical; seconds are display only. Intervals are half-open `[start_frame, end_frame)`.
* Local-first with a remote protected backend remains the recommended production topology; the adapters are the seam.

## 4. Milestone plan

| M | Deliverable | Verification |
|---|---|---|
| M1 | Precision Studio UI on sample data: player, timeline, tracks, bbox, inspector, shortcuts, save-state, plus library/athletes/datasets/evaluations/editing-review screens | Playwright interaction tests + screenshots |
| M2 | Ingest/dedup/archive/reconcile/move-survival, synthetic ffmpeg videos | node:test incl. interrupted upload, hash mismatch, event loss, cleanup simulation |
| M3 | Annotation API: drafts w/ optimistic concurrency, approval, immutable revisions, athletes/appearances, bbox keyframes | node:test + Playwright e2e persistence across reload |
| M4 | Dataset freeze, blind deterministic evaluator | determinism + isolation tests |
| M5 | EDL schema, transforms, contain/crop metrics, NOT_EVALUABLE handling | analytic synthetic tests |

## 5. Risks / open approvals

* R2 protected bucket + separate Supabase project: **needs operator approval** (new cloud resources).
* Pipeline EDL emission: **needs operator approval** (pipeline change).
* `node:sqlite` is experimental in Node 22 (prints a warning). Mitigation: all DB access isolated in `db.mjs`; swap to Postgres adapter later.
* Proxy playback and bbox over rotated sources: rotation recorded, verified with synthetic fixture only.

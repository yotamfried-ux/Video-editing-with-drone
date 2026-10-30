# Phase B status — evidence-based

Branch: `ccr-5ce1d535-e7mo2b`. **Phase B is PARTIALLY COMPLETE**: all code, schema and tests exist and pass locally; no live resource was created, no real footage processed, no production run triggered.
Legend: IMPLEMENTED = code exists · VERIFIED = executed with the evidence shown · NOT TESTED / BLOCKED as stated.

## Deliverable matrix
| # | Deliverable | Implemented | Verified (evidence) | Not verified / blocked |
|---|---|---|---|---|
| 1 | Architecture + gap analysis | yes — `phase-b/ARCHITECTURE-GAP-MATRIX.md` | repo + read-only Supabase metadata inspection | Cloudflare account not inspected (no access) |
| 2 | Protected archive | `R2Archive` (SigV4, checksums, multipart, no delete method), `mirrorArchive`, `probe-archive-protection.mjs` | 10 tests vs S3 stub: published AWS SigV4 vector, corruption in transit/at rest, multipart abort+retry, outage, credential hygiene, no object DELETE ever issued, mirror skips corrupt sources | **real R2**: NOT TESTED; **bucket+tokens**: BLOCKED (A1); retention-lock behavior unverified |
| 3 | GT database schema/migrations | `db/migrations/0001`, `db/roles.sql`, runner, `PgDb` adapter | applied to local **PostgreSQL 16**; 61+ tests pass on SQLite **and** Postgres; idempotent migration + dry-run | **Supabase**: NOT TESTED; project/schema choice BLOCKED (A2) |
| 4 | Authorization/isolation tests | `tests/pg/isolation.test.mjs` | `anon`/`authenticated`/`service_role` (BYPASSRLS) denied on every GT table/view/function; Studio role: no DELETE/TRUNCATE/DDL, no UPDATE on history, no production tables; owner blocked by triggers; evaluator reads frozen views only; static scan: no production file references Studio | live role grants/Supabase default privileges: NOT TESTED |
| 5 | Persistent Studio integration | backend selection (SQLite / Postgres, local / R2), importers, backup/restore/audit | qualification + backup tests on both backends | multi-user/RLS-per-user not in scope |
| 6 | Pipeline EDL export | `pipeline/edl_export.py` + additive hook | **EDL ↔ real ffmpeg pixels** for contain, fixed crop, follow crop (6 tests); rendering args identical on/off; failure isolation; multi-source reel offsets match `editor._events_with_rendered_timeline`; blends listed | a real pipeline run: NOT RUN (A3); reused clip-cache flows record `clip_not_recorded` (incomplete EDL is flagged, never guessed) |
| 7 | Pipeline prediction export | `pipeline/prediction_export.py` + `scripts/export_pipeline_predictions.py` + diagnostics hook | 4 tests driven by the real ledger builder: sha/frame mapping, rejected decisions + reasons, output lineage, determinism, commit/run traceability | ledger quality on real runs (`recall_status`) depends on upstream selector |
| 8 | Editing evaluation integration | importers, multi-source/mixed-mode/keyframe EDL support, blend exclusion, review API + UI | qualification test: real reels evaluated; Studio box centres agree with **actual rendered pixels** (±30 px) at 4 frames across tracked-crop and contain shots; defect cases detected from the real render (decoy athlete: `missing_surfer`+`wrong_surfer`, exact frames) | real footage: NOT TESTED |
| 9 | Test evidence | see below | | |
| 10 | Env var docs | `phase-b/ENVIRONMENT.md` | | |
| 11 | Backup/recovery docs + tooling | `phase-b/BACKUP-RECOVERY.md`, `gt-backup.mjs` | round trip + tamper refusal + integrity audit on both backends | scheduled backups on live infra: NOT SET UP |
| 12 | Pull request | see PR | | |

## Test evidence (executed in this session)
* Studio: `npm test` (SQLite) and `STUDIO_TEST_DB_URL=… npm test && npm run test:pg` (PostgreSQL 16) — see "Final runs" below.
* Pipeline: `python scripts/test_edl_export_contract.py` (6) and `python scripts/test_prediction_export_contract.py` (4).
* Browser: `npm run test:e2e` 17/17 (after Editing Review multi-source changes).

## Findings worth your attention
1. In the real pipeline, a `contain` decision is frequently **upgraded to follow-crop** by the existing `follow_crop` logic ("full_frame_readable+following_bound_track"). The EDL now makes that measurable; it is a product-contract question (contain-first), not changed here.
2. The prior single-source EDL assumption was wrong for production: reels combine clips from several sources, so `edl/v1` gained per-shot `source`, `mode`, `keyframes`, and `blends` (backward compatible; old tests unchanged).
3. R2 cannot grant an Object Read & Write token that excludes delete; deletion protection must come from bucket lock/retention and token separation (see A1).
4. Supabase's transaction pooler is incompatible with multi-statement transactions; use direct/session connections.

## Remaining work / limitations
EDL covers geometry only (logo overlay and reel fades are listed, not modeled); xfade frames are excluded rather than approximated; follow-crop keyframes are sampled at integer output frames; perception/source dimension mismatch is flagged in `notes`; variable-frame-rate and rotated sources unverified; athlete-key mapping in the evaluator is co-occurrence based.

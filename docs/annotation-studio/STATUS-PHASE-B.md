# Phase B status — evidence-based

> **Plan change 2026-10-30 (zero extra cost):** see [`phase-b/INFRASTRUCTURE-DECISION.md`](phase-b/INFRASTRUCTURE-DECISION.md). Rows 2–4 below now read: archive = local write-once + independent encrypted backups
> (R2 lock prefix and/or Hetzner append-only, subject to the read-only audits); database = local SQLite by default, Supabase `ground_truth` schema prepared and tested but **not deployed**.
> New evidence: 8 PostgreSQL isolation tests incl. a Supabase-faithful replay (non-superuser migration, live role/ACL configuration read from the catalog), `db/verify-isolation.sql`, a guard that the inference workflow holds no database-admin credential.

## Open items (as of the last CI run)
| # | Item | Status |
|---|---|---|
| 1 | EDL/prediction export workflow | **VERIFIED** — `edl-export-contract.yml` (workflow id 402168780) run #5 on head `7d01c85`: success; its log shows `4 prediction export contract tests passed` and `6 EDL export contract tests passed` |
| 2 | Run the three read-only audits (`scripts/infra-audit/`) | **BLOCKED on the operator** — they need access to R2, the Hetzner server and the REST API that this environment does not have |
| 3 | Storage architecture | **Local-first selected for development.** Implemented and tested: same-device-refusing independent backup, verification, restore drill, status warning. Offsite target (Hetzner / R2) awaits the audits and approval |

## Final state for merge review (2026-10-31, Local First approved)
Decision: **Local First** (SQLite + local write-once archive + independent-device backup). PostgreSQL/R2 remain implemented and tested but are **not** required or deployed. No cloud resource was created, no production setting changed, no cost incurred.

| Area | Status | Evidence |
|---|---|---|
| Local run / readiness | **PASS** | `docs/annotation-studio/OPERATOR-GUIDE.md`; `npm start`; browser workflow runs against a real server |
| Original footage ingested unchanged, never deleted | **PASS** | sha256 identity, write-once 0444 archive, delete triggers/no endpoint (`tests/catalog`, workflow scenario 12) |
| Sport catalog / multi-sport | **PASS** (scope in spec §20.1) | `tests/sports.test.mjs` 7/7 on SQLite **and** PostgreSQL; workflow scenarios 2,3,5,6,7,10 |
| Athlete + event + bbox annotation, GT with history | **PASS** | workflow scenarios 4,6 (immutable revisions, digest, audit) |
| Close/reopen without losing work | **PASS** | workflow scenario 8 |
| Pipeline predictions + EDL import → evaluation → report | **PASS** (synthetic) | workflow scenarios 9,10; qualification test through the real render path |
| Editing quality / contain-first | **PASS** | workflow scenario 11 (contain never scored as a crop failure); pipeline export leaves ffmpeg args unchanged (python contract tests) |
| Backup on a separate device + restore drill | **PASS** (copy simulated on one filesystem; refusal is the real `st_dev` check) | workflow scenario 13, `tests/offsite.test.mjs` 8/8 |
| GT isolation from the pipeline | **PASS** | `tests/pg/isolation.test.mjs` 8/8 on real PostgreSQL 16; API guard test |
| Local suites at head | SQLite **78/78**; PostgreSQL **77 pass, 1 skipped** (SQLite-only file-tamper test), 0 fail; PG isolation **8/8** | run in this session |
| Browser | `run.mjs` **17/17**, `workflow.mjs` **14/14** | run in this session |
| Infra audit scripts | **BLOCKED** (no access; not needed for Local First) | `phase-b/INFRA-AUDIT-STATUS.md` |
| Real footage / live infra / production run | **NOT_TESTED** (by decision) | — |
| Suggested sport, `source_sports`, stratified splits, sport-specific metrics | **NOT IMPLEMENTED** (future phase) | spec §20.1 |

Real defects found and fixed while closing this out: backup/restore silently omitted the sport registry; `gt-migrate --dry-run` could not apply a second migration (each was rolled back separately); isolation proof depended on cluster-wide role state left by an interrupted run.

Branch: `ccr-5ce1d535-e7mo2b`. **Phase B is PARTIALLY COMPLETE**: all code, schema and tests exist and pass locally; no live resource was created, no real footage processed, no production run triggered.
Legend: IMPLEMENTED = code exists · VERIFIED = executed with the evidence shown · NOT TESTED / BLOCKED as stated.

## Deliverable matrix
| # | Deliverable | Implemented | Verified (evidence) | Not verified / blocked |
|---|---|---|---|---|
| 1 | Architecture + gap analysis | yes — `phase-b/ARCHITECTURE-GAP-MATRIX.md` | repo + read-only Supabase metadata inspection | Cloudflare account not inspected (no access) |
| 2 | Protected archive | `R2Archive` (SigV4, checksums, multipart, no delete method), `mirrorArchive`, `probe-archive-protection.mjs` | 10 tests vs S3 stub: published AWS SigV4 vector, corruption in transit/at rest, multipart abort+retry, outage, credential hygiene, no object DELETE ever issued, mirror skips corrupt sources | **real R2**: NOT TESTED; **bucket+tokens**: BLOCKED (A1); retention-lock behavior unverified |
| 3 | GT database schema/migrations | `db/migrations/0001`, `db/roles.sql`, runner, `PgDb` adapter | applied to local **PostgreSQL 16**; 62 tests pass on SQLite, 61 (+1 intentionally skipped) on Postgres; idempotent migration + dry-run | **Supabase**: NOT TESTED; project/schema choice BLOCKED (A2) |
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
* Studio, SQLite: `npm test` — **62/62 passed**.
* Studio, PostgreSQL 16 (local): `STUDIO_TEST_DB_URL=… npm test` — **61 passed, 1 skipped** (the SQLite-only direct-file tamper test), 0 failed; `npm run test:pg` role-isolation tests — **4/4 passed**.
* Pipeline: `python scripts/test_edl_export_contract.py` (6) and `python scripts/test_prediction_export_contract.py` (4).
* Browser: `npm run test:e2e` 17/17 (after Editing Review multi-source changes).

## Findings worth your attention
1. In the real pipeline, a `contain` decision is frequently **upgraded to follow-crop** by the existing `follow_crop` logic ("full_frame_readable+following_bound_track"). The EDL now makes that measurable; it is a product-contract question (contain-first), not changed here.
2. The prior single-source EDL assumption was wrong for production: reels combine clips from several sources, so `edl/v1` gained per-shot `source`, `mode`, `keyframes`, and `blends` (backward compatible; old tests unchanged).
3. R2 cannot grant an Object Read & Write token that excludes delete; deletion protection must come from a bucket-lock rule (verified live by a probe before use) plus an independent second copy (see R1).
4. Supabase direct connections are IPv6-only unless a paid add-on is bought; the free route is the shared pooler in **session mode** (port 5432). (An earlier draft wrongly said the transaction pooler breaks multi-statement transactions; it is simply untested with this adapter and not recommended.)
5. In the live Supabase project the `postgres` role is a member of `pg_read_all_data`; anything holding its password (the `SUPABASE_DB_URL` secret, the dashboard) can read a same-project Ground Truth schema. The inference workflow holds no such secret (enforced by a test).

## Remaining work / limitations
EDL covers geometry only (logo overlay and reel fades are listed, not modeled); xfade frames are excluded rather than approximated; follow-crop keyframes are sampled at integer output frames; perception/source dimension mismatch is flagged in `notes`; variable-frame-rate and rotated sources unverified; athlete-key mapping in the evaluator is co-occurrence based.

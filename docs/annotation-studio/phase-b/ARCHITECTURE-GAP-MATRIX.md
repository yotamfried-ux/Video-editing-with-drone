# Phase B — Infrastructure architecture and gap matrix

Date: 2026-10-30. Base: `main` @ `f34bd9d` (PR #310). Investigation was read-only: repository inspection plus
Supabase *metadata* listing (`list_projects`, `list_tables`; no row reads, no writes). No Cloudflare access was used.

## 1. What PR #310 already delivered (reuse, do not redo)

Local Studio (`annotation-studio/`): SQLite catalog with DB-enforced immutability, write-once local archive, reconcile, drafts/revisions,
datasets, deterministic evaluator, `edl/v1` math + editing metrics, UI (7 screens). 48 unit/security tests + 17 browser scenarios, all on **synthetic** media.
It has **no** real R2, **no** Postgres/Supabase, and the pipeline emits **neither** EDL **nor** predictions.

## 2. Findings from inspection

| Area | Evidence | Consequence |
|---|---|---|
| R2 layout | `web-api/src/lib/r2-storage.ts` (`R2_BUCKET`, default `sportreel`), `integrations/r2_storage.py`; one credential set (`R2_ACCESS_KEY_ID/SECRET`) shared by web-api, pipeline, deliver/cleanup workflows | A **prefix is not a security boundary**: whoever holds that key can delete every object in the bucket |
| Cleanup | `video-storage-cleanup.ts` deletes video-extension objects under `raw/ processed/ review/ approved/ pending_payment/ pending_uploads/ previews/`; only `metadata/` is protected; same bucket, same key | Archiving originals in this bucket (even under a new prefix) is **not** protected from a mistaken/extended cleanup or a leaked key |
| Supabase | One SportReel project `sportreel` (`bcndgmymnismbxvdeetc`, eu-central-1, 24 public tables, RLS on, production data: 261 drafts, 301 source_uploads). The org's only other project is unrelated | Pipeline/web-api use the **service role** (bypasses RLS). RLS alone cannot protect GT in this project; privileges/schema/role design must |
| Existing upload dedup | `source_uploads` keyed by `storage_key`; dedup *supersedes and deletes* older duplicates | Not a permanent identity; Studio keeps its own `sources` (sha256+size) and only *reads* this as a hint (not wired, no credentials) |
| Pipeline render choke point | `pipeline/quality_preserving_framing.py`: `decide_framing` → `_resolve_track_safe_decision` → `_render_clip` (modes `contain`, fixed crop, `follow_crop` with keyframes). `editor._events_with_rendered_timeline` already computes exact per-clip output offsets incl. xfade overlap | **EDL can be derived from the exact values passed to ffmpeg** — no re-inference, no behavior change |
| Pipeline evidence | events carry `track_id`, `bbox_xyxy`, `perception_*`, `visible_track_ids`; `framing_decisions.jsonl`; `draft_decision_trace.json`; perception sidecar | Predictions can be exported from existing evidence |
| Migrations | `supabase-migrate.yml` is manual (`workflow_dispatch`, `APPLY` confirm) and reads only `supabase/migrations/` | GT migrations live in `annotation-studio/db/` — outside every production migration path |
| CI | path-filtered per-contract workflows; Studio has `annotation-studio-check.yml` | Extend with Postgres service container (free) |

## 3. Gap matrix

| # | Requirement | Existing | Missing | Reuse | Change | Security | Cost | Depends on | Validation |
|---|---|---|---|---|---|---|---|---|---|
| A | Protected R2 archive | Local write-once FS archive (`archive.mjs`) | S3/R2 adapter; separate bucket+token; lifecycle/backup docs | SigV4 pattern from `r2-storage.ts` (re-implemented in Studio, **not imported**) | `R2Archive` adapter + config; no change to pipeline | Own bucket + bucket-scoped token ≠ pipeline token; no browser creds; server-side signed GETs only | New bucket: ~$0.015/GB-mo above the free tier (verify current pricing) — **needs approval** | Operator creates bucket+token (or approves me to) | SigV4 + multipart/verify tests vs. in-repo S3 stub (executed); live probe script (**NOT run**) |
| B | Protected GT database | SQLite adapter | Postgres schema, roles, RLS, migrations, runtime adapter | DDL parity with `db.mjs` | `db/migrations/*.sql`, `db/roles.sql`, `PgDb` sync-bridge adapter | Dedicated schema + login role; `REVOKE` from `anon/authenticated/service_role`; not API-exposed | Same project: $0. **Separate project (recommended): may be $10+/mo** if plan limit reached — **needs approval** | Operator decision: separate project vs. dedicated schema | Real Postgres 16: apply migrations, immutability triggers, role-denial tests (executed locally + CI service container) |
| C | Pipeline EDL export | event-level offsets, `framing_decisions.jsonl` | per-clip geometry, assembly into per-output EDL, hash/run/commit lineage | `_events_with_rendered_timeline`, `FramingDecision` | `pipeline/edl_export.py`; one additive hook in `quality_cut_clip` (records, never alters args) | EDL contains no labels/GT | $0 | none | Synthetic: render with the real `_render_clip`, compare EDL transform to actual pixels |
| D | Prediction export | evidence in events/diagnostics | versioned schema + exporter | event dicts, `athlete_coverage` | `pipeline/prediction_export.py` | no GT access | $0 | C (lineage) | schema/contract tests; commit+run traceability |
| E | Studio consumes exports | file shapes | `import-edl`, `import-predictions`, mapping UI evidence | `edl.mjs`, `evaluate.mjs` | importers + `keyframes` in `edl/v1`, blend frames | importer validates hash against catalog; unknown sha → rejected | $0 | C, D | E2E: real render → EDL → evaluate |
| F | Pipeline cannot reach GT | static scan only | DB-level denial proof, credential separation doc | — | role tests, CI scan | core requirement | $0 | B | `service_role`/`anon` denied on real PG (executed) |

## 3a. Multi-sport requirement (spec §18, added by #311 after Phase B started) — **NOT IMPLEMENTED in this PR**

| Requirement (§18) | Current state | Gap | Plan |
|---|---|---|---|
| `sports` registry + versioned taxonomy | none; `event_type` is a fixed surfing-oriented enum in `annotations.mjs` | missing | migration `0002_sports.sql`: `sports`, `sport_event_types`, `taxonomy_version`; seed `surfing` with today's event keys so legacy data stays valid |
| `primary_sport_id` / `source_sports`, per-segment sport | none | missing | add nullable `sources.primary_sport_id` (NULL = `unknown`, **never** backfilled to surfing), segment `sport_id`; server-side sport/event compatibility validation |
| Taxonomy pinned in revisions and frozen datasets | revisions have `schema_version` only | missing | add `taxonomy_version` to revision content + dataset manifest (digest-covered) |
| Library sport badge/filter/bulk assign, inspector sport selector, Settings admin | none | UI work | extend Library/Annotate/Settings |
| Sport-separated evaluation (no cross-sport matching, per-sport denominators) | evaluator is sport-blind | missing | group by `sport_id` in `evaluateSource` totals and reports |
| Backward compatibility for surfing data | — | required | `0002` must be additive; existing 48+ tests must pass unchanged |

Impact on what *is* in this PR: the Phase B schema (`0001`) is surfing-agnostic except the `event_type` values in application code, so `0002` is additive; the pipeline exporters carry `sport` only via event type today (`predictions/v1` has no `sport` field yet — add before the first real multi-sport run). **Needs a scheduling decision** (see PR description).

## 4. Isolation decisions (recommended; need operator choice)

* **Archive:** separate R2 *bucket* + separate API token scoped to that bucket only (Cloudflare tokens can be scoped per bucket). Enable bucket-level retention/lock **if** available on the account, and **verify** with the probe script rather than assuming. Pipeline/web-api tokens must never be granted this bucket. Studio holds the only read/write token; the evaluator needs none (it reads frozen annotation exports, not footage).
* **Database:** preferred = **separate Supabase project** (blast-radius isolation incl. dashboard/service-role keys). Equivalent-in-practice fallback = same project, schema `ground_truth` owned by `gt_owner`, login role `gt_studio` (direct Postgres connection, **not** PostgREST), `REVOKE ALL` on the schema from `PUBLIC, anon, authenticated, service_role`, schema **not** added to the API's exposed schemas. Residual risk of the fallback: project-superuser/dashboard compromise and a future `GRANT … ON ALL TABLES IN SCHEMA` run by mistake. The role-denial tests below verify the fallback's grants and are reusable against a live project once approved.
* **Evaluator boundary:** role `gt_evaluator` = `SELECT` on frozen views only + `INSERT` on `evaluation_runs`.

## 5. Approvals required (not requested yet; nothing below was done)

1. Create R2 bucket + bucket-scoped token (cost above).
2. Choose separate Supabase project vs dedicated schema; apply `db/migrations` to it.
3. Real-run `pipeline-run.yml` with EDL/prediction export enabled (the export code is additive and off by default until `SPORTREEL_EXPORT_EDL=1`).

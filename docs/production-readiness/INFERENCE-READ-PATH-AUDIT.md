# Inference read-path audit (MEM-03) — 2026-11-19

**Scope:** every read the production inference process (`scripts/run_tracked.py` → bootstrap → orchestrator →
stages) can make of state that outlives a run.

**Method:** the static trace below covers Supabase `.select`, R2 `get` and `list`, local history files and caches.
`scripts/test_inference_memory_isolation_contract.py` runs negative controls against it.

**Strict mode:** `SPORTREEL_STRICT_COLD_INFERENCE=1`, set by both pipeline workflows in PR #401.

## Classification

| # | Read | Where | Carries video-specific history? | Strict cold inference | Evidence |
|---|---|---|---|---|---|
| R1 | LLM analysis / QA / identity answer cache (`/tmp/llm-cache`, restored from `actions/cache`) | `integrations/llm_cache` | **yes**: prior model answers per source hash | disabled (`enabled()` false) and cache no longer restored or saved (PR #401) | M6; PR #401 contract |
| R2 | Perception sidecar cache (content-addressed) | `perception/runtime._sidecar_cache_key` → `llm_cache` | **yes**: prior detections and tracks | disabled with R1 | M6 |
| R3 | Pre-existing `.perception.json` next to a source | `perception/runtime.ensure_sidecar_for_video` | **yes** if left by an earlier run | reused only if written during this run (mtime ≥ run start); otherwise recomputed | M7 |
| R4 | Operator notes for earlier drafts (from `reprocess_requests` → `operator_notes.json`) | `stages/feedback.get_operator_notes` → analysis prompt | **yes**: per-draft editorial instructions (190 notes in production) | closed and recorded; qualification runs also skip the reprocess stage | M1; `orchestrator._handle_reprocess_requests` |
| R5 | Structured `draft_feedback` rows (Supabase) | `stages/feedback.get_negative_feedback_hint` → analysis prompt | aggregated problem types, derived from earlier outputs | closed and recorded | M3 |
| R6 | Approval / edit history (`labels_feedback.json`) | `stages/feedback.get_all_label_injections` → analysis prompt | derived from earlier approved reels | closed and recorded | M2 |
| R7 | QA history (`qa_results.jsonl`) | `stages/feedback.get_qa_calibration_hint` → QA prompt | derived from earlier verdicts | closed and recorded | M4 |
| R8 | Manual identity decisions (`SPORTREEL_IDENTITY_REVIEW_DECISIONS`, `evaluation/identity_reviews/decisions.json`, qualification-only file) | `identity_review.load_decisions` | **yes**: per-source-pair answers | returns none; env must be empty (PR #401 gate) | M5 |
| R9 | Ground Truth, frozen holdouts, qualification and evidence files, private GT boxes | (no runtime reader) | **yes** | removed from the runner checkout (PR #401 `--prepare`) **and** refused by an open() audit hook in the inference process | M8 |
| R10 | Processed-source markers `metadata/source_state/*` | `r2_storage.processed_markers` | no: size and ETag of a raw object, which source to process | allowed (operational) | — |
| R11 | Draft ledger `metadata/draft_ledger/*` | `draft_ledger.assign_name`, `publish` | no: canonical id, name, plan digest of an upload; read only at upload, after all editorial decisions | allowed (operational idempotency) | draft-ledger contract |
| R12 | `source_uploads`, `upload_batches` | `integrations/source_uploads` | no: content-hash dedup of uploads | allowed (ingest) | — |
| R13 | `reprocess_requests` (pending) | `orchestrator._handle_reprocess_requests` | **yes** (notes) | production feature; skipped in qualification runs; notes closed by R4 in strict | — |
| R14 | `drafts`, `reels`, `athlete_follows`, `push_tokens`, `pipeline_runs` | delivery and publication (`services/delivery.py`, `supabase_uploader`) | `reels.athlete_id` is per-session; delivery runs after operator approval | outside inference | — |

## What this proves and what it does not

**Proved, in the inference process:** R1–R9 cannot reach a decision under strict mode.
- **Control runs** see each planted value. The test is therefore able to detect a leak.
- **Strict runs** do not. Each closure is written to `pipeline-debug/inference_isolation_report.json`.
- **RED:** on the PR #401 head without this patch, M1–M5 and M9 fail. History channels stay open even with strict
  mode set.

**Not proved:**
1. **Model weights:** pretrained weights and earlier GT-guided development cannot be made memoryless. This is allowed,
   and it is not holdout evidence.
2. **Network-level enforcement (measured 2026-11-19, read-only `pg_catalog`):**
   - `service_role`, the current inference credential, has **no USAGE on schema `ground_truth`** and SELECT on 0 of
     33 GT tables. GT is isolated at the database level.
   - It **can** read `public.draft_feedback` and `public.reprocess_requests`, because it bypasses RLS. For these
     tables, isolation relies on the strict-mode code closure.
   - **Prepared, not applied:** `supabase/migrations/20261119_inference_role.sql` creates role `sportreel_inference`.
     It grants exactly the tables inference writes for its own run and explicitly revokes the two history tables. It
     gives no ground_truth access and no delivery tables.
   - Strict runs use `SUPABASE_INFERENCE_KEY` when it is set. Otherwise the isolation report records
     `service_role_fallback_not_isolated`.
   - With the inference key, reprocess requests are no longer read inside inference; they need a separate pre-step.
   - Contract: `scripts/test_inference_db_role_contract.py`.
   - Applying the migration and issuing the key are owner actions.
3. **Cloud-run proof:** that a real strict cloud run closes every channel. That is shown by the isolation report of a
   real run under PR #401's workflows, which needs an approved run.

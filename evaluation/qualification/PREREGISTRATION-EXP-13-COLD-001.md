# EXP-13-COLD-001 — zero-previous-run-memory isolated pipeline evaluation

**Owner direction:** merge PR #391 then evaluate the merged pipeline as though it encounters the *same known 24 source videos* for the first time. This is NOT a fresh-footage holdout, and previously GT-informed software development is not erased.

**Starting main SHA:** `b3d0e8edf42b1fe2bfe5e7dc81bcf8e2c8af4783` (PR #391 merged after 47/50 CI success; 3 skipped).
**Experiment branch:** `experiment/cold-inference-no-memory-20261118`; exact test SHA is the PR head when the `qualrun-paid` label is applied.
**Inputs:** original verified source objects from batch `batch_2026-10-03T12-19-52_ttgvat95`, independently copied into namespace `qualification/q13-cold-no-memory-01/`.
**Scope:** no existing Review edits, no prior decisions file, no GT-v1 feed to inference; GT-v1 allowed solely in an offline evaluator AFTER the run.

## Enforced cold/inference controls
- `actions/cache/restore` for the LLM analysis cache is skipped in this qualification workflow on this branch.
- `/tmp/llm-cache` and `/tmp/llm-cache-cold-no-memory` are purged before inference on the ephemeral runner.
- `LLM_CACHE=0` bypasses the integrations.llm_cache cache for Gemini raw responses AND perception detector/tracker sidecars (pipeline/perception/runtime.py).
- `SPORTREEL_IDENTITY_REVIEW_DECISIONS=''`; production default `evaluation/identity_reviews/decisions.json` must not exist. The previous qualification-only 0097+0115 / 0074+0151 owner decisions are NOT loaded.
- Pretrained general-purpose model weights, the **trained code and previously tuned policies**, and reusable binary/python dependency caches remain unchanged. This is a cold inference test, not an untrained model.
- No changes to the frozen GT-v1, prompts, model, application logic, or baseline during the evaluation.

## Safety and cost
- Exact production pipeline entry point in isolated namespace.
- Supabase writes/RPCs denied and logged; no production R2 write/delete, no user-facing publication, no emails.
- Snapshot production before/after, abort evidence certification on any delta.
- Paid model-call ceiling **$0.80** of the owner's remaining pre-experiment **$2.273** campaign allowance; stop on cap. Expense reports are preliminary provider-estimate until billing reconciliation.
- No `reset=true`, `full_clean`, or deletion of source/Review/approved production objects.
- The previous cache store is not destroyed: it is simply unavailable to this test. Any cleanup needed is confined to the ephemeral runner.

## Pre-registered scorecard
- Compare results with EXP-11-001 and EXP-12-001 using GT-v1 *after* inference; record executed SHA and input source digests.
- Report: FULL coverage (prior 15/24); missing include seconds (prior 16.2); false/unsafe identity merges (prior 0 publishable); wrong-actor frames (prior 54); excluded frames (prior 999); correct ready-for-Review (EXP-11 4, EXP-12 3); withheld correct; split athletes; false-QA pass; all source action boundaries; cost and duration.
- Success as a *cold-run sanity check* requires all files render/decode, 0 production mutation and 0 unchecked external decisions; no confirmed wrong-identity publishable reel, and no worsening of protected metrics versus EXP-11-001 (especially correct ready-for-Review ≥4). A failure of any protected gate is an EXPERIMENT FAILURE even when the workflow is green.
- Cold runs may differ from cached runs; report both positive and negative differences without modifying thresholds or code to fit this experiment.
- Review every ambiguous multi-clip reel, 0097, 0115, 0074, 0151, 0094, 0108, 0155 and 0095 if present; decode all resulting MP4 files; emit SHA256, source lineage and contact sheets.

**Evidence levels:** cold-cache proof requires run/job logs confirming the bypass, artifact inventory and hashes. A green workflow alone is not a cold-run or media-quality certificate. There is still no unseen-footage HOLDOUT_VERIFIED claim.

**Post-run:** reset `llm_budget_usd_paid=0` on the experiment branch after cost is recorded; remove the paid label. Do not merge this experiment-only cache-bypass configuration to main.

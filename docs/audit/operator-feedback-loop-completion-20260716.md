# Operator feedback loop + editorial ranker completion — 2026-07-16

Closes out the remediation plan's Workstream G (the last item in
`docs/pipeline-quality-audit.md`'s repair plan).

## Finding: the label vocabulary and half the learning loop already existed

Before writing any code, re-reading `pipeline/candidate_ledger.py` and
`pipeline/stages/feedback.py` found this workstream's original framing stale, the
same pattern as PQ-007/PQ-008/Workstream F earlier in this pass:

- `pipeline/candidate_ledger.py` already defines `VALUE_LABELS` (14 labels),
  `OPERATOR_FEEDBACK_EVENTS` (11 events — already almost exactly the button set
  `docs/audit/self-learning-loop-audit-20260706.md` Phase 8 asks for), and
  `value_feedback_schema()` (the required-fields contract), and already
  per-event-labels every candidate via `infer_value_labels()`.
- `pipeline/stages/feedback.py` already has a working, recency-weighted,
  approval-based learning loop injecting event-type+edit patterns into future
  Gemini prompts, plus a separate freeform per-draft note loop.

What was genuinely missing: nothing connected the two to the operator app. No
Supabase table, no API route, no UI control submitted a structured feedback
event; nothing on the Python side read one back.

## What this closes

1. **Supabase**: `supabase/migrations/20260716_add_draft_feedback.sql` — new
   `draft_feedback` table (service-role only, mirrors `reprocess_requests`'
   RLS pattern). Columns: `draft_name`, `feedback_event`, `value_labels` (jsonb),
   `note`, `created_at`.
2. **web-api**: `POST /api/operator/drafts/feedback`
   (`web-api/src/app/api/operator/drafts/feedback/route.ts`) — validates
   `feedback_event` against the mirrored `OPERATOR_FEEDBACK_EVENTS` vocabulary,
   inserts a row. Typed in `web-api/src/types/operator-contracts.ts`
   (`OPERATOR_FEEDBACK_EVENTS`/`VALUE_LABELS` consts, mirroring
   `pipeline/candidate_ledger.py` — that module stays the source of truth for
   this vocabulary; keep both in sync by hand, there's no shared package).
   Mirrored again into `mobile/src/features/operator/types/contracts.ts` per
   the existing web-api/mobile contract convention.
3. **mobile**: `mobile/src/app/(operator)/review.tsx` — each draft card gets a
   row of 7 structured-feedback buttons (Wrong athlete, Duplicate athlete,
   Mixed people, Cut too early, Bad crop, Boring, Missed good moment), each
   posting to the new route. The existing freeform re-edit notes field is
   untouched — structured labels are additive, not a replacement (the audit's
   own wording: "free text is optional, not enough").
4. **Python consumer**: `pipeline/stages/feedback.py::get_negative_feedback_hint()`
   reads recent `draft_feedback` rows (via new
   `integrations/supabase_uploader.py::fetch_recent_draft_feedback()`),
   recency-weights them (reusing the existing `_decay_weight` half-life logic),
   and — once at least 3 rows exist — injects a "recent operator feedback,
   avoid repeating these problems" block into the analysis prompt, wired in
   alongside the existing `get_all_label_injections()`/`get_operator_notes()`
   injection in `pipeline/stages/analyzer.py`. Never blocks or fails the
   prompt if Supabase is unreachable (fails closed to `""`, matching the
   existing feedback-loop functions' error handling).
5. **Recall report**: `scripts/generate_missed_moment_report.py` — cross-
   references `MISSING_GOOD_MOMENT` feedback rows against that draft's
   `candidate_decision_ledger` (persisted in `reels_metadata.json`'s
   `diagnostic_artifact` by the already-installed `pipeline/candidate_ledger.py`),
   producing `missed_good_moment_count` (ROI 10's explicit ask) plus the
   dropped-candidate evidence for each flagged draft.
6. **`pipeline/editorial_value_ranker.py`**: new module, deliberately scoped
   additive/reporting-only — patches `pipeline.candidate_ledger.build_candidate_entry`
   to add `editorial_value_score`/`editorial_value_categories` fields to every
   ledger entry (composite of `infer_value_labels()` + `narrative_policy.quality_score()`).
   Wired into `pipeline/bootstrap.py` and `scripts/run_tracked.py` right after
   `candidate_ledger`'s own install call.

## Deliberately not done in this pass

- **Acting on structured feedback** (merging/dropping drafts, hard-blocking on
  a feedback label) — this pass only records and surfaces feedback. ROI 9's
  "merge same-athlete drafts or drop weaker duplicate" is a separate, already-
  deferred production-behavior change (see Workstream F's completion doc).
- **Live selection/partitioning change from the ranker score** — the ranker
  never touches `pipeline/stages/editor.py::_partition_events`/`_group_dur`.
  Same reasoning already recorded for PQ-008's `_partition_events`: changing
  what actually gets selected or how a reel is paced based on a new composite
  score is real reel-length/pacing risk that needs a real pipeline run to
  validate, not available in this sandbox.
- **`clean_takeoff`/`strong_ending`/`crowd or friend interaction`/`unique camera
  motion` value categories** — no analyzer event type or keyword term reliably
  identifies these today; inventing a keyword heuristic for them would be a
  guess, not evidence-based labeling like the other categories. Left unmapped
  rather than faked.
- **Time-windowed missed-moment matching** — `draft_feedback`'s schema
  (`draft_name, feedback_event, value_labels, note, created_at`) carries no
  time-window reference, so `generate_missed_moment_report.py` cannot claim to
  identify *which* dropped candidate was the missed moment; it surfaces the
  dropped-candidate evidence for a human to correlate against the feedback
  note instead of fabricating a match.
- **Evidence-summary-on-card** (Phase 8's other ask — primary track,
  mixed-subject risk, duplicate risk, source window shown on the draft card)
  — the report generator already computes this data, but no operator API
  currently exposes it per-draft; would need the drafts list route extended.
  Scoped out as a stretch item, not silently dropped.
- **Durable candidate-ledger storage** — `candidate_decision_ledger` still
  only lives in the ephemeral per-run `reels_metadata.json`; there's no
  Supabase table persisting it across runs, so the missed-moment report can
  only correlate feedback against a ledger from the same local run/export
  it's given, not historical runs. Would need its own Supabase table + write
  path; out of scope here.

## Verification

- `scripts/test_operator_smoke_contract.py` / `scripts/operator_smoke.py`: new
  route's missing-auth-header rejection covered like every other mutating
  operator route.
- `scripts/test_structured_feedback_contract.py`: `get_negative_feedback_hint()`
  — no injection below the row threshold, no injection/crash when the
  feedback source is unavailable, correct problem-type surfacing, recency
  decay, and analyzer wiring (source-text check).
- `scripts/test_missed_moment_report_contract.py`: synthetic
  feedback+metadata fixtures, including a draft with no ledger metadata at
  all (must not fabricate evidence).
- `scripts/test_editorial_value_ranker_contract.py`: additive-only wrapping
  (every existing candidate-entry field preserved), idempotent install, and a
  static check that the module never imports/patches
  `pipeline.stages.editor`.
- `scripts/test_bootstrap_parity_contract.py`: extended to require
  `pipeline.editorial_value_ranker` in the canonical pre-orchestrator patch
  list, so a future entrypoint missing this install is actually caught.
- `web-api`/`mobile` `tsc --noEmit`: clean.

Real-run validation is pending, per this repo's standing rule — an actual
operator tapping a structured-feedback button, a real `draft_feedback` row
landing in Supabase, and a real pipeline run's prompt actually reflecting the
injected hint are all things this sandbox cannot exercise (no live Supabase
project, no GEMINI_API_KEY, no real footage). This workstream is more
dependent on that real usage than any other in this pass, since its entire
point is closing a loop with real human input.

# Self-detection metrics completion — 2026-07-16

Closes out the remediation plan's "Workstream F" item (`scripts/generate_run_quality_report.py`
missing `qa_gate_bypass_rate`/`BUG_QA_GATE_BYPASSED` and duplicate-athlete detection).

## Finding: `qa_gate_bypass_rate` / `BUG_QA_GATE_BYPASSED` were already implemented

The remediation plan (written before this pass re-checked the code) stated these were
completely absent. That was stale. `scripts/append_qa_gate_summary_to_report.py` already
computes `qa_gate_bypass_rate` and emits `BUG_QA_GATE_BYPASSED` from the run log, is already
wired into the real pipeline via `scripts/run_pipeline_with_diagnostics.sh`, is already
covered by `scripts/test_run_quality_report_contract.py`, and has already been validated
against a real pipeline run — see `docs/audit/run-29111503822-qa-gate-bypass.md`, which shows
a real run correctly producing `qa_gate_bypass_rate = 1.0` and `BUG_QA_GATE_BYPASSED` for two
drafts with an unresolved `PREMATURE_CUT`. No code change was needed for this half of the
gap; it is documented here only to correct the plan's premise.

## Change: duplicate-athlete detection metric (new)

`generate_run_quality_report.py`'s `implementation_gaps.duplicate_athlete_metric_ready` was
hardcoded `False` and no `BUG_DUPLICATE_ATHLETE_LIKELY` classification existed, per
`docs/audit/self-detection-metrics-audit-20260706.md`'s `duplicate_athlete_violation_rate`
spec and ROI 9 in `docs/audit/run-28768826828-roi-repair-plan-20260706.md`.

`pipeline/athlete_canonicalization.py` already annotates every event with `athlete_id` and
`athlete_canonical_evidence_status`, merging clusters when *strong* evidence (a shared
cross-source `track_id`, or a pre-existing non-generated `athlete_id`) says two clusters are
the same real athlete. `scripts/build_draft_decision_trace.py` already carries these fields
through into each draft's `source_windows`. This was enough evidence, already flowing through
existing artifacts, to add a real report metric without new pipeline instrumentation.

Added to `scripts/generate_run_quality_report.py`:
- `_duplicate_athlete_likely_drafts()`: groups trace drafts by `athlete_id`, counting only
  events whose `athlete_canonical_evidence_status == "strong"`. Weak/`single_source` fallback
  ids are deliberately excluded — those are per-source hash fallbacks, not cross-source
  identity evidence, and would produce false positives under the track fragmentation already
  documented in `docs/audit/run-28768826828-roi-repair-plan-20260706.md` (205 track ids from
  one video).
- New metrics: `duplicate_athlete_likely_draft_count`, `duplicate_athlete_violation_rate`
  (matches the name specified in the self-detection-metrics audit).
- New report field: `duplicate_athlete_likely_drafts` (athlete id + the draft ids involved).
- New hard-block alert + `BUG_QA_GATE_BYPASSED`-style classification: `BUG_DUPLICATE_ATHLETE_LIKELY`.
- `implementation_gaps.duplicate_athlete_metric_ready` flipped to `True`.

### Self-review finding: naive "same athlete_id across drafts" would have false-positived on ordinary output

The first version of this change flagged any strong athlete_id spanning 2+ draft ids. Before
merging, re-reading `pipeline/orchestrator.py::_compile_clusters` showed this was wrong: one
cluster (one real athlete) routinely produces multiple output drafts on purpose — the
`"(part N)"` naming there splits one cluster's highlights across several reels — and every
resulting draft shares the same `athlete_id`. The naive version would have hard-blocked every
normal run where an athlete got more than one reel, which is likely the single most common
multi-draft-per-athlete case in this app — not a rare edge case.

Fixed by additionally requiring that the flagged drafts come from *different* source-video
pools (`draft.source_videos`, already computed per draft by
`scripts/build_draft_decision_trace.py`). Drafts split from one cluster all draw from that
cluster's shared appearance list and so share a source-video set; genuinely separate,
unreconciled draft collections for the same athlete do not. `scripts/test_run_quality_report_contract.py`
now asserts both directions directly against `_duplicate_athlete_likely_drafts()` (same-source
pair not flagged; cross-source pair flagged; weak/single_source evidence never flagged), plus
an end-to-end negative check in the existing fixture (which uses a same-source, strong-evidence
pair and must not raise `BUG_DUPLICATE_ATHLETE_LIKELY`).

Residual known gap: a single cluster whose appearances span multiple source videos could, in
principle, still have its parts allocated across different source-video subsets, which would
false-positive under this refined check too. There is currently no persisted `cluster_id`/
`reel_group_id` on draft metadata to close this precisely — closing it fully would mean adding
that identifier in `orchestrator.py`'s reel-compilation path and threading it through
`draft_identity_metadata.py` and `build_draft_decision_trace.py`, which is real production-code
surgery beyond this report-generator-scoped pass. Documented here rather than silently
implemented as if fully solved.

## Deliberately not done in this pass

ROI 9 also asks to *act* on duplicate-athlete evidence ("merge same-athlete drafts into one
collection or drop weaker duplicate") — a production behavior change, not a report metric.
The ROI plan's own guardrail says: "Do not tune duplicate-athlete logic without first
measuring track fragmentation," and that fragmentation work is still open. This pass adds
only the detection/reporting metric (informational + hard-block alert in the diagnostics
report), matching the plan's Workstream F scope. No drafts are merged, dropped, or blocked
by this change.

## Verification

- `scripts/test_run_quality_report_contract.py` extended with a fixture where two drafts
  share a `strong`-evidence `athlete_id`; asserts the new metric, report field, and bug
  classification.
- Real-run validation: pending, per this repo's standing rule — the "strong" evidence status
  requires cross-source track_id/athlete_id matches, which this sandbox cannot produce from
  real footage.

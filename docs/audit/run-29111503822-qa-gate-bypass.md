# Run 29111503822 — PREMATURE_CUT QA Gate Bypass

## Scope

- Repository: `yotamfried-ux/Video-editing-with-drone`
- Workflow run: `https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/29111503822`
- Branch: `main`
- Commit: `bb33c17134310c57a8aa9c390cf892fd536d2329`
- Purpose: validate clean-subwindow rescue and the `no_reviewable_drafts` terminal outcome added by PR #170.

## What worked

The GitHub Actions job completed successfully, including:

- storage and Supabase preflight;
- pipeline execution;
- QA re-edit task persistence verification;
- diagnostics artifact upload.

The selection prefilter evaluated four long-video candidates:

- `selection_filter_events.record_count = 4`
- `selected_for_render_count = 2`
- `discarded_count = 2`
- `clean_subwindow_rescue_count = 2`

Two broad multi-person event windows were rescued into clean single-athlete sub-windows:

1. Pink one-piece / pink longboard
   - original window: `495.0–512.5`
   - rescued window: `498.97–510.62`
   - rescued duration: `11.65s`
   - primary track: `4385`
   - primary detections: `18`
   - excluded other tracks: `1`

2. Black shorts / turquoise longboard
   - original window: `480.0–491.0`
   - rescued window: `480.0–487.28`
   - rescued duration: `7.28s`
   - primary track: `4166`
   - primary detections: `13`
   - excluded other tracks: `1`

Two additional candidates were correctly rejected with:

- `discard_cause = no_clean_subwindow_found`
- `reason_codes = [MULTI_PERSON_CLIP, NO_CLEAN_SUBWINDOW_FOUND]`

## Failure found

The run uploaded two drafts, but independent reel QA returned `FAIL` for both:

- Pink-board draft: `PREMATURE_CUT` near the end of the 11-second reel; the ride was cut abruptly and faded to black.
- Turquoise-board draft: `PREMATURE_CUT` near the end of the 7-second reel; the cut occurred while the wave was still resolving.

The run log then reported:

```text
✅ 2 draft(s) uploaded to REVIEW folder
```

The diagnostics report correctly classified this as:

- `status = fail`
- `qa_critical_defect_count = 2`
- `qa_gate_bypass_rate = 1.0`
- `BUG_QA_GATE_BYPASSED`

The draft trace, however, recorded the two drafts as unflagged and without final QA evidence. This demonstrated an execution-policy/diagnostics-policy mismatch.

## Root cause

Three policies disagreed:

1. `pipeline/stages/analyzer.py` allows `PREMATURE_CUT` to be labelled `minor` unless it truncates the best moment.
2. `pipeline/orchestrator.py::_qa_blocking` only entered the automatic re-edit loop when a QA defect was labelled `critical`.
3. `scripts/append_qa_gate_summary_to_report.py` already treated every `PREMATURE_CUT` as a hard-block quality defect.

Additionally, `_apply_qa_fixes` ignored non-critical defects before reaching its existing `PREMATURE_CUT` repair, so the `+3s` extension path never ran for a minor-labelled premature cut.

Result:

```text
PREMATURE_CUT detected
→ model severity = minor
→ no automatic re-edit
→ no QA-FLAGGED/review-required state
→ normal REVIEW upload
→ diagnostics report gate bypass
```

## Fix

Branch: `fix-premature-cut-qa-bypass`

The correction aligns runtime behavior, persisted QA state, and diagnostics:

- `PREMATURE_CUT` and `CUT_TOO_EARLY` are always product-blocking regardless of LLM severity.
- They are normalized to critical before the existing event repair function, allowing the current `+3s` extension path to execute.
- Every final clean reel receives explicit final QA diagnostics, not only flagged reels.
- Final decisions are one of:
  - `passed`
  - `passed_after_reedit`
  - `failed_nonblocking`
  - `blocked_review_required`
- If the premature cut remains after the retry limit, the draft is explicitly review-blocked and receives a persistent QA re-edit task.
- Clean or nonblocking final results no longer receive fabricated fallback approval-block reasons.
- The quality report distinguishes flagged REVIEW uploads from unsafe unflagged bypasses and uses the final draft QA trace to resolve transient pre-repair failures.

## Regression coverage

`scripts/test_premature_cut_qa_gate_contract.py` verifies:

- a minor-labelled `PREMATURE_CUT` is still blocking;
- it reaches the existing automatic repair path;
- an unresolved final is marked `blocked_review_required`;
- a technical/engagement-only FAIL is explicitly `failed_nonblocking` without an approval block;
- flagged uploads are not double-counted or reported as unsafe bypasses;
- final repaired/blocked traces clear false bypass alerts while preserving block counts and retry telemetry.

The contract is wired into Operator Smoke Check.

## Real-run acceptance criteria

A post-merge pipeline run must prove one of these safe outcomes for every final draft:

### Repaired

- QA re-edit executes for `PREMATURE_CUT`.
- Final QA no longer contains a blocking premature-cut defect.
- `qa_gate.decision = passed_after_reedit`.
- `retry_count > 0`.
- No approval-block reasons remain.

### Still failing

- QA retry limit is reached or no valid repair can be produced.
- Draft is named/recorded as QA flagged.
- `qa_gate.decision = blocked_review_required`.
- `review_required_reasons` and `approval_blocked_reasons` include `PREMATURE_CUT`.
- A durable QA re-edit task exists.

For the complete run:

- `qa_gate_bypass_rate = 0.0`
- every uploaded draft has an explicit final QA decision;
- the run remains operationally successful if all unsafe drafts are explicitly blocked;
- actual video quality must still be inspected before declaring the content issue resolved.

## Status

- Code correction: implemented on branch.
- Contract coverage: implemented and wired to CI.
- PR CI: pending.
- Real post-merge pipeline validation: pending.

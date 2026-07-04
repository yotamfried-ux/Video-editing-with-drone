# PQ-007 wave window invariant

Date: 2026-07-04

Status: audit addendum for `docs/pipeline-quality-audit.md`.

Selecting the right wave is not enough. The pipeline must also cut the selected wave correctly.

## Updated invariant

A normal draft event should contain the full visible action window:

```text
setup -> peak/action -> outcome
```

For surf footage, this means the final cut should preserve the wave entry/setup, the main maneuver or action peak, and the landing/exit/outcome. If the system cannot prove that the final cut contains this window, the event should be rejected, flagged for manual review, or excluded from a normal draft.

## Timing mistakes this must prevent

- Starting the clip after the wave setup or entry already happened.
- Ending the clip before the maneuver, landing, exit, continuation, or outcome is visible.
- Keeping long empty padding before or after the action.
- Building a teaser from an empty or weak part of the wave.
- Relying on post-render QA as the first guard against wrong cut timing.

## Required metadata

Future PQ-007 work should persist these fields or equivalent fields:

- `original_start` / `original_end`.
- `clamped_start` / `clamped_end`.
- `final_cut_start` / `final_cut_end`.
- `cut_adjustment_reason`.
- `setup_start` when detected.
- `peak_time` or `action_time` when detected.
- `outcome_end` when detected.
- `window_validation_status`.
- `window_validation_reason`.

## Required repair loop

1. Inspect `pipeline/stages/analyzer.py`, `pipeline/stages/editor.py`, and `pipeline/orchestrator.py` before changing behavior.
2. Add diagnostics for original, clamped, and final cut windows.
3. Add action-window fields when evidence exists.
4. Change duration caps so they protect the action peak and outcome.
5. Make teaser extraction sample the action peak, not empty padding.
6. Add `scripts/test_event_window_contract.py`.
7. Run Operator Smoke Check and a real pipeline run before declaring PQ-007 solved.

## Required contract tests

`scripts/test_event_window_contract.py` should prove:

- A late-start event is expanded, rejected, or flagged so setup is not lost.
- An early-end event is expanded, rejected, or flagged so outcome is not lost.
- A dead-time-only window is dropped.
- Long pre-action padding is trimmed without removing setup or peak/action.
- Long post-action padding is trimmed without removing outcome.
- A duration cap never removes the detected action peak.
- A teaser is not generated from a weak or empty part of the wave.
- Metadata explains every boundary adjustment.

## Relationship to other audit items

- PQ-006 prevents weak filler events from reaching this stage.
- PQ-008 must use the same action-window evidence when choosing climax and teaser.
- PQ-009 should treat invalid action-window metadata as a QA defect for normal drafts.
- PQ-010 should persist this timing metadata in the per-draft diagnostic artifact.

# EXP-11-001 — paid isolated run q11-paid-01: motion-supported onset (FIX-PQ-11-001)

Written and committed BEFORE the run; success and failure conditions are not edited afterwards.

| Field | Value |
|---|---|
| Experiment | EXP-11-001 |
| Gaps | PQ-05 (incomplete catch/paddle start), PA-15 (boundaries), PA-06/PA-09 (0115 paddle-in) |
| Hypothesis | Opening the cut where the stitched actor is seen MOVING back to the analyzer's setup (Core onset, surfing profile parameters) recovers paddle-in starts without adding stationary waiting. |
| Candidate | FIX-PQ-11-001: `pipeline/action_onset.py::motion_supported_onset`, `window_refinement.refine_event_window` (records `onset_motion_from_sec`), `complete_action_window_policy.extend_to_setup`, `output_qualification.action_interval` (onset is verified lead). Profiles: `pipeline/sport_profiles` (surfing onset: requires motion, 0.2 body heights/s, max lead 6 s, 1 s steps). |
| Code | Branch `ccr-3f12fc2f-pdvirt`; head = the commit that enables the paid budget (after the owner reopened #391). Pipeline code is `c9848ca5`, merged with the owner's doc commits and `main` (docs only; `e3a99d53`); no pipeline change since. Verified against the workflow run's `headSha`. |
| Data | Batch `batch_2026-10-03T12-19-52_ttgvat95`, the same 24 sources and SHA-256 as EXP-10-001; GT-v1 ae844a94, digest `b31fd9b4…27c9`, used only for scoring after the run. |
| Models | Workflow defaults, unchanged: gemini-2.5-flash source evidence, gemini-2.5-pro clustering, yolo11s/OpenVINO, botsort, stride 5. |
| Preceding free experiment | Cycle-11 replay on EXP-10-001 diagnostics (same scorer): missing include 20.4 → 16.7 s, ≥95 % rides 14 → 15, incorrect starts 8 → 7, non-GT seconds 7.47 → 7.47. Contract `scripts/test_action_onset_contract.py` and the football architecture contract pass. Alternatives rejected in replay: a cap raised to 3 s or 6 s (adds 0.9 s waiting on 0140), and stitching without motion (same). |
| New evidence a paid run gives | Rendered MP4s from the exact code with the new starts (0115, 0142), and confirmation that nothing else in the pipeline changes them. Replay cannot show the render. |
| Budget | Hard cap **$0.40** (`SPORTREEL_LLM_BUDGET_USD`, $0.05 reserve, checked before every call). Expected $0.20–0.25 (EXP-10-001: $0.206, same cache). Campaign $4; spent $1.280; remainder $2.720. |

## Success conditions (all required; quality_scorecard.py + gt_scorecard.py, same GT)
1. Production fingerprint identical.
2. missing include seconds ≤ 17.2; ≥95 % rides ≥ 15; incorrect starts ≤ 7.
3. Protected (vs EXP-10-001):
   - non-GT seconds ≤ 7.97;
   - FULL rides ≥ 14;
   - excluded frames ≤ 999;
   - publishable wrong identity = 0;
   - visibly mixed publishable reels = 0;
   - QA false passes ≤ 1;
   - publishable correct ≥ 4.
4. Spend ≤ $0.40.
5. MP4s decode cleanly. The 0115 and 0142 reels are viewed and open on the paddle-in, not on a standing surfer. The 0140 reel is viewed and does not open on stationary waiting.

## Failure conditions
Any protected metric breached, any production change, a cap breach, or a visible waiting lead-in at the start of 0140.

## Rollback
Revert FIX-PQ-11-001 (the onset wiring in window_refinement / extend_to_setup); set the paid budget to 0; record the
root cause. Nothing is merged to main and nothing is published.

## MULTI_SPORT_COMPATIBILITY (gap register §13.2)
- **Scope:** Core `action_onset.py`, `window_refinement.py`, `complete_action_window_policy.py`,
  `output_qualification.py`; profile parameters in `sport_profiles`.
- **Invariant:** the build-up belongs to the action only while the primary actor is moving; waiting does not.
- **Surf regression:** 0115 vs 0140 in replay.
- **Second domain:** football run-up fixture (O4 in `test_action_onset_contract.py`; F4 in
  `test_football_profile_architecture_contract.py`).
- **Decision:** PASS (architecture). No football accuracy is claimed.

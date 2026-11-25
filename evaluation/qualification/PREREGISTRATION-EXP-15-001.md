# Preregistration: EXP-15-001 — Complete Strict Cold-Inference & Action-Validity Qualification Run

- **Date:** 2026-11-25
- **Run ID:** `q15-cold-full-01`
- **Cohort:** `batch_2026-10-03T12-19-52_ttgvat95` (24 DJI 4K sources in isolated `qualification/q15-cold-full-01/` namespace)
- **Authorized Budget:** Hard cap `$3.50` (`llm_downstream_reserve_usd = $1.10` reserved for pairwise identity verification, two-pass visual action validity, and final QA), inside owner-authorized `$10.00` pipeline qualification budget.
- **Strict Cold Inference (`MEM-01..06`):**
  - `SPORTREEL_STRICT_COLD_INFERENCE=1`
  - `LLM_CACHE=0` (0 cross-run LLM or sidecar cache hits permitted)
  - `SPORTREEL_IDENTITY_REVIEW_DECISIONS=''` (0 prior manual identity decisions injected)
  - `evaluation/` removed from runner checkout by `assert_cold_inference.py --prepare` and blocked by runtime `open()` audit hook
- **Active Pipeline Policies Tested:**
  1. `SPORTREEL_ACTION_VALIDITY=1` (`FIX-PQ-14-002`): two-pass visual crop observer rejects failed takeoffs (`0155`) while retaining prone, kneeling, and standing rides.
  2. `FIX-PQ-14-001` + `PQ-05` early 4K onset probe: camera-motion-compensated `in_progress_from_recording_start` + 1280px early-onset recall escalation.
  3. `PQ-04` velocity-projected track stitching + `PQ-06` `last_track_sec + 1.0s` dead-water tail clamp.
  4. `FIX-PQ-14-003` 6-crop model-path identity sheet + `PQ-23` `sha256:` collision-resistant member keys + `PA-08` multi-clip subject-gate quarantine.
  5. `PQ-38` 75% reliable trajectory framing rescue + 4K BT.709 VUI color signaling.
- **Evaluation Criteria:**
  - Compare both strict `gt_scorecard.py` against untouched `gtv1_frozen.json` (`ae844a94` / `b31fd9b4...27c9`) AND `gt_adjudicated_view.py` (`ADJ-14-001`, `ADJ-14-002`, `POL-14-001`).
  - Production R2/Supabase fingerprint before vs after must be 100% identical (`0` production mutations).

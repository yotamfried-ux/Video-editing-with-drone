# EXP-08-001 — ride-validity verifier (pre-registered before any model call)

- **Hypothesis:** a narrow per-window question ("did the TARGET stand up and ride standing?") asked after selection
  rejects the 0155 failed take-off without rejecting any GT-valid ride. Box-shape heuristics were measured first and
  fail (valid top-down rides 0.92–1.05 h/w vs 0155 1.02), so a free replay cannot decide this.
- **Code under test:** `pipeline/ride_validity.py` (`verify_window`, `parse_verdict`, `decide`), prompt `ride-validity-v1`;
  harness `scripts/ride_validity_experiment.py`; executed SHA recorded from `GITHUB_SHA` in the result.
- **Model:** `gemini-2.5-flash`, temperature 0, media resolution LOW, clip = window ± 0.5 s at 4 fps, 360p proxy.
- **Input (frozen):** the 25 selected output windows of run 43920602179 + GT controls (0155 full exclude segment,
  0108 excluded tail, 0095 GT athlete segment, 0094 A tail 13.2–22 s). Job list committed:
  `evaluation/ride_validity/jobs_43920602179.json` (labels from GT-v1 ae844a94 / b31fd9b4…27c9; no boxes).
- **Repetitions:** each selected window twice (no verdict cache) → stability.
- **Metrics:** FP = GT-valid window rejected; TP/FN on GT failed take-off windows; stability; reported ride end vs GT
  end (evidence only; no cut is moved).
- **Failure conditions (any → the gate is not enabled):** ≥ 1 FP in any rep; 0155 kept in any rep; < 90 % of windows
  stable.
- **Cost cap:** $0.80 hard (estimated model cost from recorded tokens); total cycle-8 authorisation $2.00, not per retry.
- **No publication:** evaluation workflow only; never runs the pipeline, never writes R2/Supabase; JSON verdicts only.
- **Known limits:** 2 negative windows (both 0155) — a positive result is DEVELOPMENT evidence, not holdout; the
  analyzer's other false selections in other runs are not covered.

# EXP-08-002 — production identity verifier on every pair of single-source reels (pre-registered)

- **Hypothesis:** the 0097+0115 split (one GT athlete, two reels) arises because the pipeline never proposes the pair
  to the fail-closed pairwise verifier; the production verifier (`pipeline.identity_pair_consensus.verify_cluster`,
  production 6-crop sheets `runtime_quality._identity_sheet`) matches it in both orders without matching any pair of
  different GT athletes.
- **Input (frozen):** the 9 single-source reels of run 43920602179 (36 pairs); labels from GT-v1 only at scoring.
- **Metrics:** false merges (MATCH on a pair of different GT athletes) — failure condition: ≥ 1; recovered splits
  (MATCH on a same-athlete pair: 0097+0115 is the only one) — success condition: MATCH.
- **Model:** gemini-2.5-flash, temperature 0 (production verifier settings). **Cap:** $0.35 hard.
- **No publication**, evaluation workflow only; JSON verdicts only. Executed SHA = the workflow run's head SHA.
- **Limits:** one positive pair; not holdout; the run's other splits are multi-source clusters already covered by
  cycle 5's production cluster check.

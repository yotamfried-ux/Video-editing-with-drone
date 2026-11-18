# Cycle 8 — fix attempts, controlled experiments, honest outcome

**Date:** 2026-11-17 · **GT:** GT-v1 frozen ae844a94 / b31fd9b4…27c9 (unchanged) · **Runs compared:** 43583126199,
43920602179 · **Spend:** $0.380 of the new $2 authorisation (estimated from recorded tokens) · **Traceability:**
`evaluation/evidence/registry.json` → generated `PIPELINE-EVIDENCE-MATRIX.md`.

**No new pipeline run and no newly rendered MP4 this cycle.** Re-running the same sources needs `reset=true`, which
deletes the current Review drafts (destructive) → BLK-08-001, owner approval needed. Nothing below is
`RENDERED_MEDIA_VERIFIED`, `HOLDOUT_VERIFIED` or `PRODUCTION_QUALIFIED`.

## Summary

| Problem | Code change | Commit | Experiment | Before | After | Video proof | Status |
|---|---|---|---|---|---|---|---|
| Replay denominator 166 vs 167 | `scripts/binding_replay.py` (per-window replay) | `b2651c38` | EXP-08-000 @ `cfae2c10` | report 166, JSON 167 | 167 windows, 167 separable, 0 ambiguous | none (replay) | RESOLVED (addition error) |
| 0155 failed take-off selected (PA-04) | `pipeline/ride_validity.py` (gate, NOT wired) | `42609b95` | EXP-08-001, run 44067400479 | 0155 selected | verifier kept 0155 in 3/3 calls; rejected a GT-valid prone ride (0094 `d805a9b1`) 2/2 | model saw source proxy clips; no render | **FAILED, not adopted** |
| 0115 paddle-in missed (PA-09) | none in production; candidate in `scripts/paddle_in_replay.py` | `2e884ddc` | EXP-08-003 (replay) | starts within 0.5 s 15/22; 0115 +4.43 s | 18/22; 0115 −0.07 s; **0140 −0.37 → −1.77 s** | none | REPLAYED, **not adopted** (1 regression) |
| 0097+0115 split (PA-08) | `identity_pair_consensus.merge_verified_singletons` + call in `stages/identity._verify_multi_clusters` | `693e7f6a` | EXP-08-002, run 44068576343 (production verifier); contract S1–S6 | two reels | verifier MATCH on 0097+0115; 0 false merges / 34; 1 REVIEW kept apart | none (no pipeline run) | TESTED; integration blocked (BLK-08-001) |
| End of ride 0108 / 0094 (PA-06/03) | none | — | EXP-08-001 `ride_end` field | 0108 tail 2 s, 0094 A +9 s | no usable signal (median 0.8 s error, outliers 4–16 s; both tails called "still riding") | none | OPEN |
| Shared wave (FIX-PQ-07-001) | unchanged | `15a732d9` | EXP-08-000 | — | 0/167 newly blocked | none; no real crossing case | REPLAYED |

## What the experiments taught

1. **0155 is not a "did they stand" question.** GT counts prone riding as a valid ride (0094 `d805a9b1`). The
   verifier also judged 0155 as "stood up, then fell". The line between a failed take-off and a short ride needs
   the owner's written definition. The catalogue has a single failed-take-off example, so no criterion can be
   validated on it without tuning to the test.
2. **0115 is not a detector problem.** The paddler is detected from frame 0, split across the canonical, raw and
   high-res track fragments. The late cut comes from the 2 s lead-in cap. The analyzer's own `setup_start` fixes
   0115 but includes waiting on 0140. Neither box shape nor image speed separates waiting from paddling (measured).
3. **The 0097/0115 split is a candidate-generation gap.** The pair never reached the verifier. Given the pair, the
   production verifier is correct and fails closed elsewhere.

## Per-athlete product state (latest run 43920602179, scorecard + rendered-reel audit; unchanged this cycle)

- 13 GT athletes, 24 ride sources, 42 include segments: every ride source is touched by some selection
  (`rides_any_selected` 24).
- Of the 24 rides, 7 are fully covered and 9 are at least 95 % covered.
- Missing: 26.1 s of include. Boundary errors over tolerance: 17.
- Excluded content rendered: 0155 (78 samples), 0108 tail (22), 0095 (an uncatalogued rider).
- Mixed reels: 2 (0143+0152). Split athletes: 2 (0097/0115).
- Correct publishable reels: 4 (11-14 baseline: 9).

FIX-PQ-08-003 would remove one split once integrated. Nothing this cycle changes the rendered counts until a
pipeline run is approved.

## Next

- **Owner decisions:**
  - approve a `reset=true` run (BLK-08-001);
  - define "failed take-off" vs "ride";
  - accept or reject the paddle-in trade-off (+8.4 s recovered on 4 rides vs 1.4 s of waiting on 0140);
  - adjudicate 0094 13.2–16 s.
- **Free work:**
  - export per-event crop hints and `setup_start` in diagnostics;
  - add 0070 to the sequence extraction;
  - fix the 0130 clip cut, which ran past the proxy's end.

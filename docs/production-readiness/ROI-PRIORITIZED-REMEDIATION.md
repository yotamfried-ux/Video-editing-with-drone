# ROI-prioritised remediation (cycle 11)

**Inputs.**
- `scripts/quality_scorecard.py` on EXP-10-001 (run 44166232265; GT-v1 digest `b31fd9b4…27c9`, 24 rides).
- Cycle 8–11 replays.
- The gap register (§13: cross-sport rule; P0 safety overrides ROI).

**Baseline today (EXP-10-001).**
- **Coverage:** FULL 14/24, ≥95 % 14, missing include 20.4 s.
- **Waste:** excluded frames 999; non-GT seconds 7.47.
- **Boundaries:** incorrect starts 8, incorrect ends 1.
- **Identity:** wrong-actor frames 54 (crop vs GT boxes); visible mixed reels 1 (withheld); split athletes 2.
- **Publishability:** 5 / correct 4; QA false pass 1, QA false reject 6.

## Scoring

`ROI = benefit × P(success) × generalisation factor / (cost units × risk factor)`

| Term | Scale |
|---|---|
| benefit | 1–5: quality impact on correct, complete reels, weighted by rides/athletes affected |
| P(success) | 0–1: from the free evidence available now |
| generalisation factor | 1 + 0.25 × (G − 1), G = 1–5 reuse across sports |
| cost units | 1 = free replay / contract, 2 = paid run of about $0.20, 3 = new model or annotation work |
| risk factor | 1–3: regression risk |

P0 safety items are thresholds: they are fixed first, whatever their ROI.

| Priority | Gap IDs | Expected benefit | Generalization | Cost | Risk | ROI | Next experiment |
|---|---|---|---|---|---|---|---|
| **P0 gate** | PQ-02, PA-11 (auto-publishable false merge) | prevents wrong-athlete reels | 5 (any sport) | done | — | threshold | FIX-PQ-10-001 MEDIA_VERIFIED (EXP-10-001): keep; validate a verifier on lookalike negatives before any multi-source auto-publish |
| 1 | PQ-05, PA-06/PA-09, PA-15 starts (0115, 0142, 0104, 0162, 0152, 0097, 0070, 0094) | replay −3.7 s missing, ≥95 % +1, starts 8→7, 0 new waiting | 5 (build-up = motion; football O4/F4) | 1 (free) + 2 (paid render proof) | 1 | **4.5** (B5 × 0.8 × 2.0 / (1.5 × 1)) | **Done:** EXP-11-001 (run 44252428407, $0.228) met every pre-registered condition: FULL 14→15, missing 20.4→16.2 s. Next: an independent holdout before calling it qualified |
| 2 | PQ-01, PQ-33, PA-01, PA-04 (0095 uncatalogued rider; 0155 failed take-off; QA false pass) | −1 QA false pass; −379 / −476 excluded frames | 4 | 3 (needs owner decision PA-01 / a validity signal) | 2 | 1.3 | Owner decision on uncatalogued riders; ActionValidity on onset/motion evidence + more negative GT |
| 3 | PA-08, PQ-03 (0097+0115 split) | one reel instead of two (one athlete) | 5 | 1 (owner review path exists) | 1 | 3.0 if the owner approves request `758fe7783e9c` | Owner decision; then a free replay with the approved decision |
| 4 | PQ-06, PA-03, PA-15 ends (0094 tail 13.2→22.5, 0108 excluded tail, 0070 gap, 0151 early end) | −7.47 s non-GT, −144 excluded frames, −1 incorrect end | 4 | 3 (EXP-10-002 failed; no reliable end signal) | 3 | 0.8 | Owner adjudication 0094 (13.2 vs 16 s); end-of-action evidence from a per-frame ride-state model (profile evaluator) |
| 5 | PQ-17, PQ-40, PA-07 (cross-source identity verifier precision) | auto-confirm correct multi-source reels (6 withheld correct) | 5 | 3 (labelled lookalike negatives, model choice) | 3 | 1.0 | Build a negative-pair set (≥ 30 lookalike pairs) before any verifier experiment |
| 6 | PQ-19–22, PQ-26, PQ-37, PQ-38, PQ-41 (render/re-edit integrity) | guard against content loss in re-edit | 5 | 1–2 | 2 | 1.6 | Re-edit no-loss contract on rendered EDL diffs (free) |
| 7 | PQ-09, PQ-25, PQ-27, PQ-31, PQ-39, PA-13 (stability, retries, cache) | reproducibility; no duplicate drafts on paid retry | 5 | 1 | 2 | 1.9 | PA-13: stable draft keys / incomplete-run supersede, tested in a Gate A paid-retry variant |
| 8 | PQ-30 (surf dependencies in Core) | lower cost of adding a sport | 5 | 1 per module | 1 | 2.5 | Move prompts and the QA-defect filter into profiles (architecture doc §3) |
| 9 | PA-14 (shadowed orchestrator compile) | removes a trap for future fixes | 3 | 1 | 1 | 2.0 | Delete or mark the shadowed copy; contract on the active path |
| 10 | PA-16 (time-attributed mixed metric) | trustworthy GO metrics | 5 | done | — | done | `scripts/quality_scorecard.py` reports visible vs time-attributed mixing |

## Order after re-ranking

The initial hypothesis was boundaries → validity/QA → identity → integrity → stability. The numbers keep boundary
starts first (highest ROI, free evidence already positive). Three changes follow from the data:

1. **0097+0115 (identity, priority 3)** moves up because the remaining cost is an owner decision, not engineering.
2. **Boundary ends (priority 4)** move down because EXP-10-002 showed the obvious signal fails, so P(success) is low
   until a ride-state evaluator exists.
3. **Cross-source verifier precision** stays low ROI until negative pairs are labelled.

## Corrections recorded in cycle 11

The cycle-10 PA-15 "overrun" figures for 0142, 0118, 0146, 0126, 0115 and 0104 were wrong. I had compared windows with
the single largest include segment, but GT rides are runs of contiguous include segments (wave_ride + maneuver +
wipeout). Measured correctly:
- **Real end defects:** 0094 tail, 0108 excluded tail, 0070 inter-ride gap, 0151 early end.
- **Real start defects:** the eight late starts listed in priority 1.

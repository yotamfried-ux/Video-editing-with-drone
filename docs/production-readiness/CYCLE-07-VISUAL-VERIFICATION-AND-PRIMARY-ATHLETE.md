# Cycle 7 — visual verification from real video and primary-athlete binding

**Date:** 2026-11-17 · **GT:** GT-v1 frozen (unchanged) · **Runs:** 43583126199 (baseline), 43920602179 (latest) ·
**Spend:** $0 (no Gemini call, no pipeline run) · **Traceability:** `evaluation/evidence/registry.json` →
`PIPELINE-EVIDENCE-MATRIX.md`.

## What was seen, not inferred

Sequences of every 6th source frame (~10 fps) were extracted read-only from R2 for 0094, 0095, 0097, 0108, 0115,
0143, 0151, 0152 and 0155 (EVD-07-001). Offline, the live GT athlete boxes, each run's EDL subject track and the
rendered crop were drawn on every frame (EVD-07-002), and the sheets were viewed in sequence.

| Case | Seen | Classification |
|---|---|---|
| 0095 | Two surfers on one wave. The GT athlete (pink board) is excluded as `no_meaningful_action`; both runs follow the **other** rider (white board), consistently, all clip long. That rider is not catalogued. | POLICY_AMBIGUOUS (owner: reels for uncatalogued riders?) |
| 0155 | Takeoff lying/kneeling, crouched, back to prone ~6.5 s — no standing ride. 11-16 renders all of it in A's reel; the tracking is on the right person. | PIPELINE_DEFECT (GT correct) |
| 0108 | Still riding at the last frame; no outcome visible (GT `missing_landing` after 6.82 s). Both runs render to ~8.5 s. | PIPELINE_DEFECT vs owner decision 2 |
| 0094 | A's reel stays on A (no switch) but runs to ~22 s; A stands in whitewater to ~16 s, prone after; GT ends A at 13.2 s, and from 16.9 s the GT ride is the other athlete's. | GT_DISCREPANCY_SUSPECTED (13.2–16 s) + PIPELINE_DEFECT (16–22 s) |
| 0151 | Three-rider party wave. 11-14 followed a non-GT rider; 11-16 follows the GT athlete. The fall is at ~5.0–5.5 s (corrects the earlier "6.2–6.9 s"). 11-16 misses the 6.1–7.6 s aftermath. | PIPELINE_DEFECT (11-14), OK + short end (11-16) |
| 0143 / 0152 | Same look (white T-shirt, dark shorts, pink board). Not separable from pixels; GT says two athletes. | INSUFFICIENT_EVIDENCE → stays REVIEW |
| 0097 / 0115 | One athlete under different light (backlit vs front-lit); 11-16 splits into two reels. | PIPELINE_DEFECT (C) |
| 0115 start | Paddling from the first frame; the reel starts at 4.5 s (actor track starts 5.51 s, detector misses the prone paddler). | PIPELINE_DEFECT (A) |

## Primary athlete on a shared wave

`scripts/primary_athlete_audit.py` walks every rendered shot every 6 source frames. It records which GT athlete the
subject box is inside, identity switches, whether the crop shows that athlete, and the GT decision of the frame
**for that athlete** (FIX-PQ-07-002). In 11-16, 24 of 25 shots follow one GT athlete with 0 switches and the crop
showing them. The exception, 0095, follows an uncatalogued rider consistently.

Scenario contract `scripts/test_primary_athlete_binding_contract.py`, run through the production binding and
continuation functions:
- **Green before the fix:** primary left/right, occlusion, a larger and central second surfer, two actions on one
  wave, the primary falling while the other rides on (the end is not chained to the other surfer), and a second
  surfer never being a reason to reject.
- **Red before the fix:** P5. Two surfers crossing at the analyzer's single crop hint were bound by a silent
  tie-break.

**FIX-PQ-07-001** (`perception/runtime._binding_separability`): such a binding is now reported ambiguous
(`actor_tracking_status=ambiguous` → `PRIMARY_ACTOR_UNCLEAR`), so it blocks with a reason. A runner-up counts only
when all of these hold:
- it is a different body (median IoU < 0.3 over shared frames);
- it is co-present for at least 25% of the bound track's window;
- it is as close to the hint as the bound track;
- it is within 10% of it on the ranking.

Controlled replay over every selected window of seven stored runs (167 windows; corrected from an earlier addition error of 166, see EXP-08-000):

| Version of the rule | Real windows marked ambiguous |
|---|---|
| hint + ranking only | 39 / 49 (duplicate canonical/raw boxes of the same person) |
| + same-body test | 1 / 49 (0104) |
| + co-presence | 0 / 167 |

The co-presence condition was set after seeing 0104, so this is development evidence. The hint is a proxy because
crop hints are not exported. The blocking branch is synthetic only, since GT-v1 has no real crossing.

## Not done / blocked

- No paid run: nothing is PRODUCTION_QUALIFIED. No HOLDOUT_VERIFIED: every source used here was also used in
  development.
- Overlay videos need the private GT boxes, so they are not in CI or in the repository. Durable storage needs an
  approved option: an R2 `evidence/` prefix or a Supabase read secret in CI (BLK-07-001).
- Owner decisions needed: PA-01 (0095), PA-03 (0094 GT end), and the PA-07 REVIEW outcome.
- Comparison: 43583126199 has no per-event actor tracks for the binding replay of the start rule (`NOT_COMPARABLE`
  in cycle 5). Its EDLs do carry subject tracks, so the primary-athlete audit compares both runs.

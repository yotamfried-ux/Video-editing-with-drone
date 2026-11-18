# Pipeline output vs the owner's Ground Truth, runs 2026-11-10 … 2026-11-16

Frozen GT-v1 (`evaluation/ground_truth/gtv1_frozen.json`, 24 sources, 24 physical rides, 13 athletes) against the
diagnostics of nine production runs on the same 29-file batch. Measured with `scripts/gt_product_check.py`
(window level, final reels as the manifest lists them). Raw files: the runs' `pipeline-diagnostics-<id>` artifacts.

## Product-level result per run

| Run | Commit | Rides covered | Reels | Mixed reels | Split athletes | Published | **Correct** | Wrong athlete | Non-ride | Correct withheld |
|---|---|---|---|---|---|---|---|---|---|---|
| 42891165218 (11-10) | `45fd944` | 23/24 | 12 | 3 | 1 | 7 | 4 | 2 | 1 | 3 |
| 43013005072 (11-11) | `090c97f` | 23/24 | 12 | 3 | 1 | 10 | 6 | 2 | 2 | 1 |
| 43203677423 (11-12) | `17b5fe4` | 24/24 | 13 | 3 | 2 | 12 | 7 | 3 | 2 | 1 |
| 43303438106 (11-12) | `041eadb` | 24/24 | 14 | 2 | 2 | 13 | 9 | 2 | 2 | 1 |
| 43397405813 (11-13) | `6362b1b` | 24/24 | 13 | 2 | 1 | 11 | 8 | 1 | 2 | 1 |
| **43583126199 (11-14)** | `7d6b544` | 24/24 | 13 | 2 | 1 | 12 | **9** | 1 | 2 | **0** |
| 43710581656 (11-15) | `9a03610` | 24/24 | 14 | 2 | 2 | 10 | 7 | 1 | 2 | 3 |
| 43816344303 (11-16) | `2b7d4cf` | 24/24 | 14 | 2 | 2 | 10 | 7 | 1 | 2 | 3 |
| 43920602179 (11-16) | `a11b401` | 24/24 | 14 | 2 | 2 | 5 | 4 | 0 | 1 | 6 |

Run 43583126199 is the baseline (`evaluation/ground_truth/baseline.json`). Selection was identical, window for
window, in the last three runs: the drop on 11-16 is in what was allowed to publish.

## Causes

1. **Verified athletes withheld (11-16, PR #389, fixed here).** `identity_evidence.member_key` keyed members by the
   run-local integer `_clip_index` when the verifier's evidence was recorded, and by the file name at the release
   gate (after `_strip_internal_fields` drops `_clip_index`). Every image-verified multi-source athlete failed the
   gate as `kept_together_unconfirmed (conflicting_track_ids)`: 0070+0108, 0160+0163, the five-source A7 reel, the A2
   reel and 0143+0152. Reproduced in `scripts/test_gt_product_check_contract.py` (R1).
2. **New interval rules withheld GT-correct rides (11-16, PR #390, adjusted here).** 0074 (GT ride to the last
   frame; track lost 1.5 s before the recording end) and 0094's A3 ride (2.09 s detection gap vs a 2.0 s limit).
   The rules caught none of the GT errors they were meant for (0095, 0108 tail).
3. **0155 selected since 11-15 (analysis cache rebuilt).** The 11-15 run re-analysed every source (1,570 s, no code
   change in perception or the analyzer); the new Gemini answer reports a ride for 0155 person_A, where the 11-14
   answer said `no_complete_action`. Cached since; it joins A2's reel. Not fixed by code here.
4. **0097 / 0115 split since 11-15.** Same athlete in GT. Until 11-14 post-processing merged them; the per-clip
   descriptions of the 11-15 analysis ("dark swimsuit" vs "no shirt") no longer pass the structured merge.
5. **Never fixed in any run:** 0095 (no ride) published; 0108 tail (144 excluded frames); 0143 + 0152 merged (two
   athletes; the image verifier confirms it every run); 0094's first window runs into A3's ride; boundaries off by
   ~1.2–2 s.

## Prevention

`GT Product Check` runs after every successful `Run Pipeline` run and on demand, and fails when a run is worse than
the baseline on rides covered, correct publishable reels, mixed reels, split athletes, wrong or non-ride published
reels, or non-ride selections. Inference code never reads the GT (contract G3).

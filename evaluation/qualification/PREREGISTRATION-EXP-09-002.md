# EXP-09-002 — paid isolated qualification run q9-paid-02 (pre-registered before launch)

## Why a second run
EXP-09-001 (q9-paid-01, run 44085419164, commit cdb77b9c, $0.225) FAILED its pre-registered identity conditions:
0097+0115 were rendered as two reels, and 0143+0152 (two GT athletes) were rendered together in one reel (withheld
from publication as IDENTITY_UNCONFIRMED, but still one reel). Diagnosis, from the run's own identity trace:

* the pairwise image verifier made **0 calls**. Every multi-source cluster ended as an identity review request with
  reason `identity_sheet_has_fewer_than_6_crops`, although every person's sheet in the trace has 6 crops.
  `_resolve_model_appearance` (the model-clustering path used in production) dropped the crop count, so every
  appearance carried `_sheet_crops = 0` (FIX-PQ-09-001). The earlier contracts set `_sheet_crops: 6` by hand.
* the model clustering DID put 0097+0115 together; `_split_impossible_clusters` split them on the text attributes
  (`wetsuit_vs_bare_or_swimsuit_conflict`: "dark swimsuit" vs "no shirt"). The singleton verifier (FIX-PQ-08-003)
  could re-join them, but the next `_split_impossible_clusters` pass would split them again: a cluster covered by
  both-orders image evidence is now exempt from the description-attribute split; same-clip and number conflicts still
  split (FIX-PQ-09-002).
* RED -> GREEN: `scripts/test_identity_model_path_sheet_contract.py` fails 4 checks on cdb77b9c, passes after the fix.

## Same inputs
Same batch `batch_2026-10-03T12-19-52_ttgvat95` (24 verified sources, same SHA-256), new namespace
`qualification/q9-paid-02/`, GT-v1 ae844a94 digest b31fd9b4…27c9 used only after the run, for scoring.

## Budget
$2 total. Spent: cycle 8 $0.380, q9-paid-01 $0.225. Remainder $1.395. Cap for this run: **$0.90**
(enforced before every model call by `check_llm_budget`, reserve $0.05). Estimate: analysis $0.22 + cluster
verification (23 pairs × 2 orders) + singleton pairs (≤ 45) ≈ $0.45–0.65.

## Success conditions (all required)
1. 0097+0115 in ONE reel containing both rides, with pairwise identity evidence.
2. 0143+0152 NOT in one reel.
3. No new mixed reel relative to q9-paid-01 (the 0094-window mix is a known, separate gap).
4. Production fingerprint unchanged (`production_snapshot_compare.json` identical).
5. Spend ≤ $0.90.

## Failure conditions
Any GT-different athletes merged with pairwise evidence (false merge); any production change; cap breach.
A pass here is NOT `RENDERED_MEDIA_VERIFIED` until the merged MP4 has been decoded and viewed.

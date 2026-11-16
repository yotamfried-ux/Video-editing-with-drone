# Cycle 1 — measurement system (M0/M1): strict GT scorecard

**Budget config:** MAX_FIX_CYCLES=6, MAX_QA_REEDIT_ATTEMPTS_PER_REEL=2, MAX_PAID_PIPELINE_RUNS=0, MAX_EXTRA_SPEND_USD=0. No paid run, no GT edit, no production write, no merge of #391.
**Base:** main `eaa81b9`. **Gaps:** PQ-07, 08, 13 (partly), 16, 19 (flagged), 21, 36. **Status:** PATCHED · TESTED · REPLAYED (historical artifacts). Not MEDIA_VERIFIED, not HOLDOUT_VERIFIED.

## What was built
`scripts/gt_scorecard.py` + `scripts/test_gt_scorecard_contract.py` (11 contracts S1–S11). Evidence unit is the rendered window of each manifest part (`source_sha256` + interval). Differences from PR #391's draft checker, each with a test:

| Draft defect (PQ) | Draft behaviour (reproduced) | Scorecard |
|---|---|---|
| 50 % = "covered" (07) | a ride with 50 % selected counts as covered | ANY / ≥50 / ≥95 / FULL buckets + missing seconds per ride; FULL needs both boundaries ≤0.5 s |
| overlap double-count (21) | overlapping windows add up | interval union; overlap reported as `duplicate_ride_frames` |
| `excluded_frames_selected` unguarded (08) | not in REGRESSION_KEYS | guarded, union per source |
| missing metric skipped (36) | `compare({"published_correct": None}, …)` → no regression | missing/None is an error, exit 2 |
| mean boundary error only | mean hides worst ride | max, p95, count over 0.5 s, per ride, in seconds |
| file-name lineage (16) | basename string + 60 fps constant | per-event `source_sha256`; exact rational fps; legacy basenames mapping to ≠1 sha are BLOCKED |
| "correct" ≠ "ride preserved" | correct reel could hold 50 % of a ride | `rides_recalled_published_full` = FULL ride inside a publishable *correct* reel |

Red evidence: the draft logic, run on the same synthetic cases, returns covered=1 for a 58 % ride, counts the overlap, reports 2 excluded frames without guarding them, and passes a `None` metric. The scorecard fails each (S1–S6).

## Replay of the two comparator runs (artifacts of runs 43583126199 and 43920602179, same definitions)
Evidence level: `historical_artifact_replayed`. Run 43583126199 uses legacy `action_lineage` (unique-basename mapping), 43920602179 uses per-event sha lineage. No media was viewed.

| metric | best 43583126199 | latest 43920602179 |
|---|---:|---:|
| rides ANY / ≥95 % / FULL (of 24) | 24 / 10 / 7 | 24 / 9 / 7 |
| **rides recalled in a publishable correct reel (FULL)** | **3** | **0** |
| published / published_correct | 12 / 9 | 5 / 4 |
| correct reels withheld | 0 | **6** |
| non-ride windows | 1 | 2 |
| excluded frames selected | 517 | 999 |
| boundary max / p95 (s); count >0.5 s (of 48) | 3.94 / 2.79; 17 | 4.44 / 2.00; 17 |
| mixed reels / split athletes | 2 / 1 | 2 / 2 |
| missing seconds (24 rides) | 29.8 | 26.1 |

Independent reproduction of #391's reported 9 and 4 correct reels, mixed (2), split (1→2). New facts the old metrics hid:
1. Even the "best" run is far from the targets: only 7 of 24 rides are FULL, 17 of 48 boundaries exceed 0.5 s, 3 rides are fully preserved in a correct published reel.
2. The latest run is worse on 7 protected metrics versus the best; `correct_reels_withheld` 0 → 6 matches PQ-11/10 (identity-evidence lineage).
3. Worst rides in the latest run: `250c3592…#R1` 4.49 s missing, `b62c8aa0…#R0` 4.44 s late start, `5f7ba69f…#R0` 2.49 s late start (candidates for PQ-05).

## Not claimed
- Ride unit is still the heuristic (same athlete, ≤3-frame gap, PQ-19); no `ride_uid` adjudication exists.
- GT-v1 file is copied byte-for-byte from PR #391 (`gtv1_frozen.json`, dataset digest `b31fd9b4…`, 24 sources / 13 athletes, asserted by S11). It has not been re-approved by the owner against the Annotation Studio.
- Run 43725044948 and the other 5 batch inputs are not scored. 0 unknown-source windows appear in both runs.
- Tracking metrics (HOTA/IDF1): NOT_MEASURABLE, no frame-level actor boxes in the GT.

## Next (cycle 2 proposal, free only)
First failing stage for the largest protected-metric loss is identity-evidence lineage (6 withheld-correct): isolate PR #391's `member_key` fix as its own PR with a source-sha key and a same-basename/different-sha negative (PQ-10/23), replayed on the frozen manifests. Then boundaries (PQ-05/06) on frozen sidecars.

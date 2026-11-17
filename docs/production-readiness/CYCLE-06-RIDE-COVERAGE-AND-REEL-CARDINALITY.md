# Cycle 6 — ride coverage and reel cardinality (work in progress)

**Status legend:** PATCHED / TESTED / REPLAYED / SIMULATED / MEDIA_VERIFIED / HOLDOUT_VERIFIED. Nothing below is MEDIA_VERIFIED or HOLDOUT_VERIFIED.
**Base:** PR #396 head after `e0e349c`. **GT:** GT-v1 (`gtv1_frozen.json`, 24 sources / 13 athletes), unchanged. Ride unit = heuristic (PQ-19).
**Reproduce:** `python scripts/athlete_ride_matrix.py --run-dir <run artifacts> --out evaluation/matrix/<run>`; contract `scripts/test_athlete_ride_matrix_contract.py` (also checks the matrices against the committed scorecards: FULL rides, excluded frames, split athletes).

## 1. Athlete × Ride × Stage matrix (the base measurement)
Full per-ride tables (track / candidate / selected / rendered fractions, boundary errors, first stage that lost frames, reel membership with QA and blocking reasons): `evaluation/matrix/<run>.md|json`.

### Latest run 43920602179
| GT athlete | GT rides | rides FULL | reels | cardinality | outcome | excluded frames |
|---|---:|---:|---:|---|---|---:|
| 0d12c8b8 | 1 | 1 | 1 | MIXED | reel_blocked | 0 |
| 144c217d | 3 | 1 | 1 | ONE_REEL | reel_blocked | 144 |
| 42f8772b | 1 | 0 | 1 | MIXED | reel_blocked | 0 |
| 6c84aed0 | 5 | 3 | 1 | ONE_REEL | reel_blocked | 0 |
| 6e81fe5b | 1 | 0 | 1 | ONE_REEL | reel_blocked | 0 |
| 8627f3bf | 1 | 0 | 1 | ONE_REEL | reel_blocked | 0 |
| 8b1c2b0e | 2 | 2 | 1 | ONE_REEL | reel_blocked | 0 |
| 8ef1161d | 1 | 0 | 1 | ONE_REEL | publishable | 0 |
| 9524ac02 | 4 | 0 | 1 | MIXED | reel_blocked | 476 |
| b9818a21 | 1 | 0 | 1 | ONE_REEL | publishable | 0 |
| c53ef74d | 2 | 0 | 2 | SPLIT | publishable | 0 |
| d805a9b1 | 1 | 0 | 2 | SPLIT | reel_blocked | 476 |
| ed0d45c3 | 1 | 0 | 1 | ONE_REEL | publishable | 0 |

Summary: `{"A_first_loss_by_stage": {"event_candidate_window": 16, "selection_dedup": 1}, "A_rides_in_no_reel": 0, "A_rides_not_full": 17, "B_athletes_with_excluded_frames": 3, "B_excluded_frames_total": 1096, "B_excluded_frames_union": 999, "C_mixed_reel_athletes": 3, "C_split_athletes": 2, "D_athletes_without_reel": 0, "athletes_publishable": 4, "athletes_reel_blocked": 9, "gt_athletes": 13, "gt_rides": 24, "rides_full": 7}`

### Best historical run 43583126199
| GT athlete | GT rides | rides FULL | reels | cardinality | outcome | excluded frames |
|---|---:|---:|---:|---|---|---:|
| 0d12c8b8 | 1 | 1 | 1 | MIXED | publishable | 0 |
| 144c217d | 3 | 2 | 1 | ONE_REEL | publishable | 144 |
| 42f8772b | 1 | 1 | 1 | MIXED | publishable | 0 |
| 6c84aed0 | 5 | 2 | 1 | ONE_REEL | publishable | 0 |
| 6e81fe5b | 1 | 0 | 1 | ONE_REEL | publishable | 0 |
| 8627f3bf | 1 | 0 | 1 | ONE_REEL | publishable | 0 |
| 8b1c2b0e | 2 | 1 | 1 | ONE_REEL | publishable | 0 |
| 8ef1161d | 1 | 0 | 1 | ONE_REEL | publishable | 0 |
| 9524ac02 | 4 | 0 | 1 | MIXED | reel_blocked | 0 |
| b9818a21 | 1 | 0 | 1 | ONE_REEL | publishable | 0 |
| c53ef74d | 2 | 0 | 1 | ONE_REEL | publishable | 0 |
| d805a9b1 | 1 | 0 | 2 | SPLIT | publishable | 0 |
| ed0d45c3 | 1 | 0 | 1 | ONE_REEL | publishable | 0 |

Summary: `{"A_first_loss_by_stage": {"event_candidate_window": 17}, "A_rides_in_no_reel": 0, "A_rides_not_full": 17, "B_athletes_with_excluded_frames": 1, "B_excluded_frames_total": 144, "B_excluded_frames_union": 517, "C_mixed_reel_athletes": 3, "C_split_athletes": 1, "D_athletes_without_reel": 0, "athletes_publishable": 12, "athletes_reel_blocked": 1, "gt_athletes": 13, "gt_rides": 24, "rides_full": 7}`

## 2. What the data says about the four problems (both runs, GT-v1)
**A — rides not fully in a reel.** No GT ride is absent from the output (rides in no reel: 0 in both runs). 17 of 24 rides are not FULL in each run, and the first stage that loses them is the *event window* (selected window = candidate window = rendered window). In the latest run **16 of the 17 miss the START** (late by 0.5–4.4 s) while the end is exact (end error 0.0 for 16); one ride (`e01a61`) is cut by `duplicate_source_window_before_render` and ends 1.47 s early. The cycle-5 source-limited start rule moved 9 starts in a replay of this run (FULL 7→15, no regressions); it is in the code but has not run in a real pipeline run.
**B — excluded content in reels.** Latest run 999 excluded frames (best run 517) in exactly three reels: `0161251_0108` tail 144 frames after the ride end (the known 0108 tail), and two **whole sources that GT marks as excluded and that contain no GT ride at all** (`0160431_0095`: 379 frames, `0165153_0155`: 475 frames). The analyzer selected a `wave_catch` there (score 9 and 7, canonical evidence `weak`, like all 23 true rides, so that field does not separate them). `0095` is in a reel marked publishable by the pipeline (`published_nonride`). Root cause: an analyzer false positive that no later gate rejects; the existing evidence has no discriminating signal.
**C — one athlete in several reels.** Latest run: 2 split athletes (`c53ef74d`, `d805a9b1`) and 3 athletes sharing a reel with another GT athlete (`0d12c8b8`+`42f8772b` = the 0143+0152 false pair, now correctly blocked IDENTITY_UNCONFIRMED; `9524ac02`+`d805a9b1` share a 5-action reel). Best run: 1 split athlete and the same 0143+0152 reel published (false merge). The split reels are blocked for `PRIMARY_ACTOR_UNCLEAR`, `track_gap_identity_continuity_unproven` or `IDENTITY_UNCONFIRMED`, i.e. identity evidence, not packing.
**D — athlete without a reel.** None in either run (0 silent absences). The real problem is different: in the latest run **9 of 13 athletes have only blocked reels** (4 publishable); the best run published 12 of 13 but included the false 0143+0152 merge and a non-ride reel.

### 2b. Can perception separate the two excluded-only sources? (REPLAYED on the frozen sidecars of run 43920602179)
Longest track per source (activity state / score / displacement / mean velocity / duration / main equipment / equipment association):
`0095` (no GT ride): active / 1.00 / 0.376 / 0.110 / 6.3 s / surfboard / 0.72; `0155` (no GT ride): active / 1.00 / 0.436 / 0.138 / 7.8 s / surfboard / 0.82.
Sources with GT rides range over active / 0.73–1.00 / 0.20–0.82 / 0.05–0.21 / 6.1–25.9 s / surfboard / 0.16–0.97. **Every value of the two negatives lies inside the range of the true-ride sources**, so no perception-derived threshold can reject them without also rejecting true rides. With two negative sources any new threshold would be fitted to them. They need a visual/semantic check (what the clip shows, and why the owner excluded it: Annotation Studio notes are not in GT-v1) or the next filming day as holdout. Not fixed, and I will not add a threshold.

## 3. Statuses so far
| Item | Status |
|---|---|
| Matrix tool + contract (A/B/C/D, per-ride first-loss stage), agrees with scorecards | PATCHED · TESTED · REPLAYED (two frozen runs) |
| Source-limited start (cycle 5) | PATCHED · TESTED · REPLAYED (not in a real run) |
| Fail-closed identity merge incl. 6-crop sheet (cycle 5) | PATCHED · TESTED · REPLAYED |
| Non-ride source false positives (0095, 0155), 0108 tail, 0115 start, split reels | REPRODUCED on frozen artifacts; **not fixed** |
| MEDIA_VERIFIED / HOLDOUT_VERIFIED | **BLOCKED** (see below) |

## 4. Blockers and decisions needed
1. **Viewing rendered media.** This environment cannot show me video frames: artifacts cannot be downloaded through the egress proxy and media must not go to public GitHub artifacts. Independent visual verification therefore needs either a private path I can read (a private bucket or viewer under existing R2 permissions) or you viewing the reels; I will not mark MEDIA_VERIFIED from a manifest.
2. **GT currency.** The matrix uses GT-v1 (digest `b31fd9b4…`). If Annotation Studio has changed since (new includes/excludes), the dataset must be re-frozen and re-approved before I measure against it.
3. **Non-ride sources.** A separating signal for 0095/0155 needs either a model look at the clip or a ride-presence check from perception; with only two negative sources any threshold would be overfit. Needs the new filming day as holdout.
4. **Paid runs / spend.** None used in this cycle so far. Estimated Gemini headroom ≈ $0.36 of the approved $2.

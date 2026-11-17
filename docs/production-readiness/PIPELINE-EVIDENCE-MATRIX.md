# Pipeline evidence matrix

Generated from `evaluation/evidence/registry.json` by `scripts/build_evidence_matrix.py` — do not edit by hand.
GT: GT-v1 frozen, dataset ae844a94, digest b31fd9b4…27c9 (unchanged). Runs compared: baseline 43583126199, latest 43920602179.

## Fixes (Gap → root cause → fix → commit → experiment → before/after → evidence → status)

### FIX-PQ-07-001 — Primary-athlete binding reports an inseparable second surfer as ambiguous instead of a silent tie-break

- **Gap:** PA-05 · **Classification:** PIPELINE_DEFECT · **Status:** `REPLAYED`
- **Root cause:** pipeline/perception/runtime._best_primary ranks tracks by a composite with a single timeless crop hint; two surfers crossing at the hint tie and max() picks one silently
- **Fix:** [Code: pipeline/perception/runtime.py::_binding_separability](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/pipeline/perception/runtime.py). _binding_separability: runner-up that is a different body (median IoU < 0.3 over shared frames), co-present for >= 25% of the bound track's window, as close to the hint (<= 0.06, within 0.03) and within 10% on the ranking -> track_binding_status=ambiguous, actor_tracking_status=ambiguous (-> PRIMARY_ACTOR_UNCLEAR via primary_actor_policy). Every event also records track_binding_status / runner_up / evidence.
- **Commit:** 15a732d9dbcfe889cc68d64cc9f8589471e27f9d
- **Experiments:** [EXP-07-001 red/green P1-P8](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/scripts/test_primary_athlete_binding_contract.py) (red 95eb149; green 15a732d), [EXP-07-002 historical binding replay](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/evaluation/evidence/binding_replay_2026-11-17.json) (denominator reconciled: 167; per-window re-run evaluation/evidence/binding_replay_2026-11-17_reconciled.json)
- **Before:** P5 bound track 1 with no flag; real windows: n/a
- **After:** P5 ambiguous + PRIMARY_ACTOR_UNCLEAR; P1-P4, P6-P8 unchanged; 0/167 real windows newly blocked
- **Evidence:** EVD-07-004, EVD-07-005
- **Limits:** Crop hints are not exported to diagnostics, so the replay uses the bound track's position at the event middle as the hint (proxy). The co-presence condition was added after seeing 0104 in run 43583126199: development data, not holdout. No real crossing case exists in GT-v1, so the blocking branch is synthetic-only (SIMULATED, not MEDIA_VERIFIED). Denominator reconciled to 167 (EXP-08-000). the real crossing branch remains synthetic-only. No new rendered MP4 or independent holdout.

### FIX-PQ-07-002 — EDL/GT sampled audit counts frame decisions for the selected athlete, not any other athlete

- **Gap:** MEAS-01 · **Classification:** VERIFIED_CORRECT · **Status:** `REPLAYED`
- **Root cause:** First version of primary_athlete_audit took any athlete's include segment as include for the frame; 0094's A reel showed 3.6 s outside GT while ~9 s are outside A's own segments (d805a9b1's ride overlaps)
- **Fix:** [Code: scripts/primary_athlete_audit.py::gt_decision](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/scripts/primary_athlete_audit.py). gt_decision(..., athlete) counts only segments of the shot's primary GT athlete
- **Commit:** 15a732d9dbcfe889cc68d64cc9f8589471e27f9d
- **Experiments:** [EXP-07-003 corrected historical EDL/GT audit](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/evaluation/primary_athlete/43920602179.json) (also baseline run 43583126199)
- **Before:** 0094 A shot 'none' 36/200 samples
- **After:** 0094 A shot 'none' 90-92/200 samples (11-14 / 11-16), matching the overlay (EVD-07-002)
- **Evidence:** EVD-07-003, EVD-07-002
- **Limits:** Correction validated against source-frame/GT overlays from the historic EDL, not against a decoded final MP4 produced by the fixed pipeline. Do not label the corrected candidate RENDERED_MEDIA_VERIFIED or PRODUCTION_QUALIFIED.

### FIX-PQ-08-001 — Ride-validity gate after selection (0155 failed take-off)

- **Gap:** PA-04 · **Classification:** PIPELINE_DEFECT · **Status:** `FAILED`
- **Root cause:** Analyzer answer for 0155 changed on cache rebuild (11-15); no later check of whether the target actually rode
- **Fix:** [pipeline/ride_validity.py @42609b95](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/42609b95880194308505e7534e8caf981717e484/pipeline/ride_validity.py): verify_window / parse_verdict / decide; reject only on high-confidence 'never stood'. NOT WIRED into the pipeline.
- **Commit:** 42609b95880194308505e7534e8caf981717e484
- **Experiments:** EXP-08-001 (run 44067400479 @42609b95), contract scripts/test_ride_validity_contract.py V1-V7
- **Before:** 0155 selected in 43920602179
- **After:** verifier kept 0155 in 3/3 calls and rejected a GT-valid prone ride twice
- **Evidence:** EVD-08-001
- **Limits:** Premise wrong: GT counts prone riding (0094 d805a9b1) as valid, so 'stood up' is not the validity criterion; 2 negative windows only. Not adopted; no further prompt iteration on the same negatives (would tune on the test).

### FIX-PQ-08-002 — Paddle-in start: analyzer setup_start beyond the 2 s cap when a same-body chain proves presence (candidate)

- **Gap:** PA-09 · **Classification:** PIPELINE_DEFECT · **Status:** `REPLAYED`
- **Root cause:** Not detector recall: the paddler is detected from frame 0 but split across track fragments; complete_action_window_policy.extend_to_setup caps the lead-in at 2 s and bounds it by the bound track's first detection
- **Fix:** Replay-only candidate [scripts/paddle_in_replay.py @2e884ddc](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/2e884ddc/scripts/paddle_in_replay.py); production code unchanged
- **Commit:** 2e884ddc
- **Experiments:** EXP-08-003
- **Before:** within 0.5 s: 15/22; 0115 +4.43 s
- **After:** within 0.5 s: 18/22; 0115 -0.07 s; 0140 -0.37 -> -1.77 s (regression)
- **Evidence:** EVD-08-003, EVD-08-004
- **Limits:** NOT ADOPTED: one regression on a negative control (analyzer setup_start includes waiting on 0140). Needs an owner decision on the trade-off or a waiting/paddling signal; no render.

### FIX-PQ-08-003 — Verify cross-source pairs of single-source clusters (0097+0115 split)

- **Gap:** PA-08 · **Classification:** PIPELINE_DEFECT · **Status:** `TESTED`
- **Root cause:** Description-based clustering kept one athlete apart under different light; pairwise verifier only checks clusters it is given
- **Fix:** [pipeline/identity_pair_consensus.py::merge_verified_singletons @693e7f6a](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/693e7f6a9bc1dcc243851e57367cfdff654ffabe/pipeline/identity_pair_consensus.py), called from [pipeline/stages/identity.py::_verify_multi_clusters](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/693e7f6a9bc1dcc243851e57367cfdff654ffabe/pipeline/stages/identity.py); all-MATCH groups only, pair cap SPORTREEL_SINGLETON_PAIRS_MAX=45
- **Commit:** 693e7f6a9bc1dcc243851e57367cfdff654ffabe
- **Experiments:** EXP-08-002 (run 44068576343 @58bb8a15: production verifier, before the merge function existed), contract scripts/test_singleton_pair_merge_contract.py S1-S6 (red on old path), identity contracts unchanged green
- **Before:** 0097 and 0115 in two reels (43920602179)
- **After:** verifier: 0097+0115 MATCH, 0/34 false merges among different/unlabelled pairs, 1 REVIEW kept apart
- **Evidence:** EVD-08-002
- **Limits:** The model experiment ran the unchanged production verifier at 58bb8a15; the merge function (693e7f6a) is proven by contract only. No pipeline run / rendered merged reel yet (blocked: BLK-08-001). Single positive pair; not holdout. Added cost ~ $0.19 per 36 pairs per run.

## Gaps

| ID | Case | Product | Classification | Status | Finding | Next |
|---|---|---|---|---|---|---|
| PA-01 | 0095 | B (exclude segment in a reel) / primary athlete | POLICY_AMBIGUOUS | `MEDIA_VERIFIED` | Two surfers on one wave. GT has one catalogued athlete (6c84aed0, pink board, left), excluded as no_meaningful_action. Both runs render a reel that follows the OTHER rider (white board, centre) for the whole clip with no identity switch; that rider has no GT segment or box. | Use owner-annotated target-athlete identity for GT audit; source-only evidence indicates current reel follows a different, uncatalogued rider. Keep existing GT-v1 exclude and do not edit or mark resolved without adjudication. No automatic publish based on two-surfer presence alone. |
| PA-02 | 0151 | primary athlete / A (coverage) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Three-rider party wave. 11-14 followed a shirtless rider who is not the GT athlete (WRONG_PERSON); 11-16 follows the GT athlete (dark wetsuit). The GT athlete falls at ~5.0-5.5 s (earlier note '6.2-6.9 s' corrected). 11-16 window ends 6.14 s and misses the aftermath to 7.6 s (GT second segment). | The binding in 11-14 followed the analyzer's person choice; not reproducible without the 11-14 hint. Keep 0151 end unchanged (no global extension, per owner). |
| PA-03 | 0094 | B / boundary | GT_DISCREPANCY_SUSPECTED | `MEDIA_VERIFIED` | A's reel (9524ac02) stays on the right surfer (no switch) but runs ~9 s past A's GT end (13.2 s): standing in whitewater to ~16 s, prone/crouched after; from frame 1010 GT's include belongs to d805a9b1, not to A. | Split decision: 13.2-16 s GT end contested, owner must adjudicate; 16-22 s prone whitewater after meaningful action is candidate pipeline tail error. Keep GT-v1 unchanged and create GT-v2 proposal only with consent. |
| PA-04 | 0155 | B (exclude segment in a reel) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Takeoff lying/kneeling, crouched, drops prone ~6.5 s: no standing ride. GT exclude is correct. 11-16 renders all 7.8 s inside A's (9524ac02) reel; tracking follows the right person. | Needs a stand-up evidence requirement or a pinned analysis cache; any detector change needs a held-out set (no fitted thresholds). |
| PA-05 | synthetic | primary athlete | PIPELINE_DEFECT | `REPLAYED` | Crossing surfers with an inseparable hint were bound by tie-break without a flag. | Red/green test passed on FIX-PQ-07-001@15a732d9; replay denominator reconciled (167, EXP-08-000); no decoded new render or real crossing holdout. EVD-07-004/005 only. |
| PA-06 | 0108 | B (exclude segment in a reel) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Rider is still riding at the last frame (9.0 s); no outcome visible, matching GT missing_landing for 6.82-9.2 s. Both runs render up to ~8.5 s (21-22 exclude samples). | Owner decision 2 (cycle 5): the ride ends with the action, content after 6.82 s excluded. Fix needs action-state evidence (CYCLE-03); no global shortening. |
| PA-07 | 0143+0152 | C/identity | INSUFFICIENT_EVIDENCE | `BLOCKED` | Merged into one reel in both runs. Side-by-side crops: white T-shirt, dark shorts, pink board in both; pixels cannot separate them. GT says two athletes. | Stays REVIEW (owner policy); never auto-published as one athlete. |
| PA-08 | 0097+0115 | C (two reels for one surfer) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Crops consistent with one athlete (shirtless, dark shorts, light-blue board); 0097 is backlit (silhouette), 0115 front-lit, which explains the analyzer's 'dark swimsuit' vs 'no shirt'. 11-16 splits them into two reels. | Fail-closed identity (#396) routes such pairs to owner REVIEW; an automatic merge needs pairwise consensus evidence, not a description match. |
| PA-09 | 0115 start | A (missing include: paddle-in) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Reel starts 4.5 s; GT include from 0.07 s (paddle-in, owner policy: include the relevant paddle-in). Sequence shows paddling from the first frame, standing ~8 s. | Perception recall for prone paddlers, evaluated on held-out rides. |
| PA-10 | 0070 | boundary | INSUFFICIENT_EVIDENCE | `IDENTIFIED` | ~2.8 s of the rendered 0070 shot is outside any GT segment (both runs). Not yet viewed. | Add 0070 to the next sequence extraction. |

## Primary-athlete scenarios

| ID | Scenario | Result | Status |
|---|---|---|---|
| P1 | primary on the left | PASS | `TESTED` |
| P2 | primary on the right | PASS | `TESTED` |
| P3 | temporary occlusion 1.5 s | PASS | `TESTED` |
| P4 | other surfer larger and central | PASS | `TESTED` |
| P5 | surfers swap positions (cross at the hint) | RED -> GREEN (FIX-PQ-07-001) | `REPLAYED` |
| P6 | separate actions on one wave | PASS | `TESTED` |
| P7 | primary falls, other continues | PASS (end not chained onto the other surfer) | `TESTED` |
| P8 | second surfer alone is no reason to reject | PASS | `TESTED` |
| P9 | same surfer across several videos | covered by scripts/test_identity_consensus_integration.py (#396) | `TESTED` |
| REAL | real multi-surfer reels (0094, 0095, 0151, 0155, 0108...) | 11-16: 24/25 shots follow one GT athlete with 0 identity switches; the exception (0095) follows an uncatalogued rider consistently | `MEDIA_VERIFIED` |

## Evidence

| ID | Kind | What | Where |
|---|---|---|---|
| EVD-07-001 | frame_sequence | Every 6th source frame (~10 fps, 960 px) of 0094 0095 0097 0108 0115 0143 0151 0152 0155, file name = source frame number | GitHub Actions run 44062679003, artifact visual-review-sequences (id 14318098891, expires 2026-12-01) |
| EVD-07-002 | tracking_overlay | Overlay frames, 10 fps proxy MP4 and 2 fps contact sheets per source: GT athlete boxes (green include / red exclude / magenta outside segments), pipeline subject box and rendered crop for 11-14 (white/cyan) and 11-16 (yellow/gold), banner with frame, GT decision and rendering reel | Generated offline from EVD-07-001 + EDLs of both runs + live GT boxes; GT boxes are not committed (private annotations). Sent to the owner in the session; durable storage pending (see BLK-07-001) |
| EVD-07-003 | metric | Frame-level primary-athlete audit of every rendered EDL shot | evaluation/primary_athlete/43583126199.json|md, evaluation/primary_athlete/43920602179.json|md |
| EVD-07-004 | contract | Primary-athlete binding scenarios P1-P8 (synthetic tracks through the production binding functions) | scripts/test_primary_athlete_binding_contract.py |
| EVD-07-005 | replay | Historic binding replay across seven runs; zero newly ambiguous windows out of 167 (denominator reconciled 2026-11-17: the report's 166 was an arithmetic error; per-run 23+23+24+24+24+24+25=167; re-run with per-window output in binding_replay_2026-11-17_reconciled.json); crop hints are proxied. Not a production or holdout proof. | evaluation/evidence/binding_replay_2026-11-17.json |
| EVD-07-006 | visual_identity | GT-box crops side by side: 0143 vs 0152 and 0097 vs 0115 | derived from EVD-07-001 (session scratch); sent to the owner |
| EVD-08-000 | replay | Binding-separability replay re-run with per-window output: 167 windows (7 runs), 167 separable, 0 ambiguous; reconciles the 166/167 denominator (166 was an addition error) | evaluation/evidence/binding_replay_2026-11-17_reconciled.json |
| EVD-08-001 | model_experiment | EXP-08-001 ride-validity verifier on 25 selected windows x2 + GT controls: FAILED pre-registered conditions (0155 kept 3/3, 2 FP on the GT-valid prone ride of d805a9b1 in 0094, stable 24/24); $0.186 | GitHub Actions run 44067400479, artifact identity-pair-experiment-ridevalid id 14320754713 (sha256:e6f6691dc7bff00368dc156bb885e4b5025910369e0056f048a057ce687c42f6); copy evaluation/ride_validity/exp08_001_result_run44067400479.json |
| EVD-08-002 | model_experiment | EXP-08-002 production pairwise identity verifier on all 36 pairs of the 9 single-source reels of 43920602179: 0097+0115 MATCH (only same-athlete pair), 0 false merges, 1 REVIEW (different athletes, not merged); $0.1943 | GitHub Actions run 44068576343, artifact id 14321178678 (sha256:e632cd30d35e0338be960fe7cc5e61a275cb735935f80e12d45a8e90faeaac1a); copy evaluation/identity_experiment/cycle8_exp08_002_singleton_pairs.json |
| EVD-08-003 | replay | EXP-08-003 paddle-in start candidate vs current code on 43920602179: 22 rides, 4 improved (0115 +4.36 s, 0094 +2.0, 0142 +1.2, 0070 +0.8), within 0.5 s 15->18, 1 regression on negative control 0140 (+1.4 s waiting); 43583126199 NOT_COMPARABLE (no per-event tracks) | evaluation/boundary_experiment/exp08_003_paddle_in_replay_43920602179.json |
| EVD-08-004 | measurement | Negative results: detector box h/w does not separate standing ride from failed take-off (valid top-down rides 0.92-1.05 vs 0155 1.02); neither box shape nor image speed separates waiting from paddling. Detector DOES see the 0115 paddler from frame 0 (tracks 3/10003/10043 inside the GT box), correcting the cycle-3 recall root cause | cycle-8 report (session measurement on 43920602179 sidecars + private GT boxes; aggregate only) |

## Blockers

- **BLK-07-001** Durable storage of overlay videos: the overlays need the private GT boxes, which are not in CI and not committed. Options: (a) owner approves writing evidence objects to R2 under an evidence/ prefix, (b) a Supabase read secret in CI. Both need explicit approval.
- **BLK-07-002** Owner decisions: PA-01 (reels for uncatalogued riders), PA-03 (0094 GT end 13.2 s vs standing to ~16 s), PA-07 REVIEW outcome.
- **BLK-07-003** No controlled candidate pipeline run or decoded final render yet. On 2026-11-17 owner authorized a NEW capped experiment campaign of up to $2 incremental total; do not spend without per-run enforcement and attribution. This is not a GO or automatic authorization to publish.
- **BLK-08-001** End-to-end integration (pipeline run -> new EDL -> rendered MP4 -> Review screen) for FIX-PQ-08-003 and later fixes: re-running the same 24 sources needs Run Pipeline with reset=true, which moves PROCESSED->RAW and DELETES current REVIEW drafts (destructive) and lands drafts on the operator Review screen. Requires the owner's explicit approval. Estimated model cost ~$0.5-0.7 (warm cache: logged $0.23 for 43920602179 + identity/singleton calls).

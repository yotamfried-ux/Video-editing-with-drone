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

- **Gap:** PA-08 · **Classification:** PIPELINE_DEFECT · **Status:** `FAILED`
- **Root cause:** Description-based clustering kept one athlete apart under different light; pairwise verifier only checks clusters it is given
- **Fix:** [pipeline/identity_pair_consensus.py::merge_verified_singletons @693e7f6a](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/693e7f6a9bc1dcc243851e57367cfdff654ffabe/pipeline/identity_pair_consensus.py), called from [pipeline/stages/identity.py::_verify_multi_clusters](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/693e7f6a9bc1dcc243851e57367cfdff654ffabe/pipeline/stages/identity.py); all-MATCH groups only, pair cap SPORTREEL_SINGLETON_PAIRS_MAX=45
- **Commit:** 693e7f6a9bc1dcc243851e57367cfdff654ffabe
- **Experiments:** EXP-08-002 (run 44068576343 @58bb8a15: production verifier, before the merge function existed), contract scripts/test_singleton_pair_merge_contract.py S1-S6 (red on old path), identity contracts unchanged green
- **Before:** 0097 and 0115 in two reels (43920602179)
- **After:** verifier: 0097+0115 MATCH, 0/34 false merges among different/unlabelled pairs, 1 REVIEW kept apart
- **Evidence:** EVD-08-002
- **Limits:** The model experiment ran the unchanged production verifier at 58bb8a15; the merge function (693e7f6a) is proven by contract only. No pipeline run / rendered merged reel yet (blocked: BLK-08-001). Single positive pair; not holdout. Added cost ~ $0.19 per 36 pairs per run. | Cycle 9 integration: never effective in a real run. q9-paid-01: verifier dead (model-path _sheet_crops=0). q9-paid-02 (verifier enabled): 0097+0115 still two reels; the stage most likely skipped (14 single-source clusters -> 91 candidate pairs > cap 45; inferred, the skip line is not in the captured log). REVALIDATION_REQUIRED.

### FIX-PQ-09-001 — Keep the identity sheet crop count on the model-clustering path

- **Gap:** PA-11 · **Classification:** UNSAFE_REVERTED · **Status:** `FAILED`
- **Root cause:** _resolve_model_appearance dropped sheet_crops, so every production appearance carried _sheet_crops=0 and the pairwise verifier refused every pair (0 calls in q9-paid-01)
- **Fix:** pipeline/stages/identity.py @2c86d3a2 (REVERTED in the cycle-9 closing commit)
- **Commit:** 2c86d3a2c61e1e45f9a2e725505fd724331b69a8
- **Experiments:** contract test_identity_model_path_sheet_contract.py RED 4 / GREEN 0 (removed with the revert), EXP-09-002 run 44121013654
- **Before:** verifier dead; multi-source clusters withheld unconfirmed; 0143+0152 one reel, not publishable
- **After:** verifier live; 0143+0152 false MATCH stamped and PUBLISHABLE; 0112 athlete split into 4
- **Evidence:** EVD-09-002, EVD-09-003, EVD-09-004
- **Limits:** The verifier (both-orders, 6-crop sheets, gemini-2.5-flash) cannot separate the 0143/0152 lookalikes; enabling it converts a withheld reel into a published wrong-identity reel. Fail-closed (dead verifier) is safer until the verifier is fixed.

### FIX-PQ-09-002 — Image-verified clusters are not re-split on description attributes

- **Gap:** PA-08 · **Classification:** NO_EFFECT_REVERTED · **Status:** `FAILED`
- **Root cause:** _split_impossible_clusters re-applies wetsuit_vs_bare_or_swimsuit_conflict after verification, undoing an image MATCH (0097 'dark swimsuit' vs 0115 'no shirt')
- **Fix:** pipeline/stages/identity.py @2c86d3a2 (REVERTED with FIX-PQ-09-001)
- **Commit:** 2c86d3a2c61e1e45f9a2e725505fd724331b69a8
- **Experiments:** contract S2/S3 (removed with the revert), EXP-09-002: no effect observed (0097+0115 never reached a verified cluster)
- **Before:** 0097+0115 split
- **After:** 0097+0115 split
- **Evidence:** EVD-09-003
- **Limits:** Only meaningful once a trustworthy verifier exists.

### FIX-PQ-10-001 — Model-only visual consensus never auto-publishes a multi-source reel

- **Gap:** PA-11 · **Classification:** CANDIDATE_IMPROVED · **Status:** `MEDIA_VERIFIED`
- **Root cause:** EXP-09-002: both-orders 6-crop MATCH for two GT athletes (0143/0152) became an identity-gate pass
- **Fix:** pipeline/real_identity_gate.py::_evidence_may_autopublish (default off; SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH=1 reserved for a validated verifier)
- **Commit:** 8992e067760602a94f95c79ba1d0a5eadf815637
- **Experiments:** RED->GREEN scripts/test_identity_autopublish_policy_contract.py (4 fails on f299a5a9), Gate C replay EVD-10-003, EXP-10-001 run 44166232265 (conditions met)
- **Before:** q9-paid-02: 0143+0152 publishable
- **After:** EXP-10-001: 0 wrong-identity publishable; 0143+0152 rendered but withheld (viewed); correct published 4 (= q9-paid-01)
- **Evidence:** EVD-10-003, EVD-10-005
- **Limits:** Multi-source reels need an owner operator_review to publish; correct merges (0126+0140, 0070+0108) are withheld too.

### FIX-PQ-10-002 — _stable_track treated _clip_index 0 as missing

- **Gap:** PA-11 · **Classification:** BUG_FIX · **Status:** `TESTED`
- **Root cause:** str(0 or '') == ''
- **Fix:** pipeline/real_identity_gate.py::_source_of
- **Commit:** 8992e067760602a94f95c79ba1d0a5eadf815637
- **Experiments:** P3 in test_identity_autopublish_policy_contract.py
- **Before:** same-source same-track cluster from clip 0 never passed
- **After:** passes
- **Evidence:** 
- **Limits:** Rare case (one athlete twice in clip 0).

### FIX-PQ-10-003 — Text-attribute split of a model-proposed grouping raises an owner identity review request

- **Gap:** PA-08 · **Classification:** CANDIDATE_IMPROVED · **Status:** `REPLAYED`
- **Root cause:** 0097+0115 grouped by the model, split on 'dark swimsuit' vs 'no shirt'; the proposal was discarded silently
- **Fix:** pipeline/stages/identity.py::_text_attribute_split_reviewed
- **Commit:** 8992e067760602a94f95c79ba1d0a5eadf815637
- **Experiments:** RED->GREEN scripts/test_text_split_review_request_contract.py (4 fails on f299a5a9), EXP-10-001 (evaluated only if the clustering groups 0097+0115)
- **Before:** 0097+0115 two reels, no review path
- **After:** EXP-10-001: PENDING review request for exactly 0097+0115 (and 0074+0151); owner decision still required
- **Evidence:** EVD-10-005
- **Limits:** Needs an owner decision; no model call; does not merge on its own.

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
| PA-11 | 0143+0152 | identity | ROOT_CAUSE_CONFIRMED | `MITIGATED` | The production pairwise verifier gives a both-orders MATCH for the 0143/0152 lookalikes (GT: two athletes) at 6-crop sheets; the identity gate then passes the reel as publishable. In every earlier production run the verifier was effectively dead on the model path (sheet crop count lost), so its live precision was never measured end to end. | Do not enable the verifier for auto-publish. Options: operator review for every multi-source cluster (current fail-closed state), or a verifier redesign validated on more lookalike negatives before any paid run. Cycle 10: FIX-PQ-10-001 withholds model-only consensus (EXP-10-001); the verifier itself is still not trustworthy. |
| PA-12 | isolation | qualification | MOSTLY_PROVEN | `TESTED` | Isolated qualification runs proven non-destructive (3 runs, fingerprints identical). Not yet proven: same-namespace retry idempotency and an explicit mid-run crash. Cycle 10 Gate A (run 44148876075): retries and three hard crashes PASS; limits: paid-retry draft-name drift and a publishable partial not exercised. | Free dry run with qualrun-dry re-using q9-dry-02, and a dry run killed mid-stage; compare fingerprints and namespace object counts. |
| PA-13 | retry | review drafts | RISK_IDENTIFIED | `IDENTIFIED` | Draft object keys come from the model's athlete description + the date. A crash after some uploads, retried on another day or with different model descriptions, leaves the first drafts in review/ next to the new ones (duplicates). Not exercised by Gate A (free runs reuse cached descriptions). | Key drafts by a stable athlete/run identity, or record a run draft ledger and supersede drafts of an incomplete run (no deletion). |
| PA-14 | code | pipeline | ROOT_CAUSE_CONFIRMED | `IDENTIFIED` | pipeline/orchestrator._compile_clusters is replaced at startup by pipeline/context_qa_gate.compile_clusters_with_context_qa; changes made only in the orchestrator copy are inert (Gate A run 1). | Remove or clearly mark the shadowed copy; contracts must assert the active path. |
| PA-15 | 0094/0108/0118/0126/0142/0146 | boundary | ROOT_CAUSE_CONFIRMED | `FAILED` | Windows overrun GT rides widely, not only 0094/0108: end overrun 0142 10.0 s, 0094 9.3 s, 0126 3.5 s, 0146 3.2 s, 0115 2.9 s, 0160 2.6 s; pre-roll 0146 4.9 s, 0118 4.7 s, 0142 4.6 s. The analyzer's own windows (e.g. 0142 3.2-22.5 'rides for a very long duration') drive them. EXP-10-002 board-loss rule rejected. | A validated end-of-action signal (per-frame ride state) on more data; owner adjudication of 0094 13.2-16 s. |
| PA-16 | scorecard | measurement | MEASUREMENT_LIMIT | `IDENTIFIED` | gt_scorecard 'mixed_reels' attributes by time overlap with any GT ride in the source, not by who is in the crop: 0094's single-rider reel counts as mixed. The primary-athlete audit (crop vs GT boxes) is the visible-mix measure. | Report both; consider a crop-aware mixed metric. |

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
| EVD-09-001 | isolated_run | Isolation proof, dry run q9-dry-02 (run 44078257676 @2d2595a0, $0): 25 reels rendered under qualification/q9-dry-02/review/; production fingerprint (R2 raw/review/approved/pending_payment/previews/metadata/source_state + Supabase drafts/draft_publishability/reels/reprocess_requests/pipeline_status) identical before/after; ledger: 52 R2 writes all namespaced, 204 Supabase writes blocked, 24 dedup decisions read-only, 52 LLM calls refused, reprocess stage skipped. NOT yet proven: same-namespace retry idempotency, explicit mid-run crash. | artifact qualification-diagnostics-q9-dry-02-44078257676 (production_snapshot_compare.json, qualification_ledger.jsonl) |
| EVD-09-002 | isolated_run | EXP-09-001 q9-paid-01 (run 44085419164 @cdb77b9c, $0.225/cap $1.20, GT-v1 ae844a94 digest b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9): production fingerprint identical; 14 reels. Pre-registered conditions FAILED: 0097+0115 two reels; 0143+0152 (two GT athletes) one reel (withheld IDENTITY_UNCONFIRMED). Diagnosis: pairwise verifier made 0 calls (every review request: identity_sheet_has_fewer_than_6_crops). Scorecard: FULL 14, >=95% 14, missing 20.4 s, excluded frames 999, mixed 2, splits 2, published 5 / correct 4. | artifact qualification-diagnostics-q9-paid-01-44085419164 (identity_trace.json, publishable_reel_manifest.json, llm_cost.json) |
| EVD-09-003 | isolated_run | EXP-09-002 q9-paid-02 (run 44121013654 @2c86d3a2, $0.469/cap $0.90, GT-v1 ae844a94 digest b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9): production fingerprint identical; 17 reels; verifier active (64 consensus calls). Pre-registered FAILURE: 0143+0152 (GT 0d12c8b8 vs 42f8772b) stamped pairwise MATCH and marked publishable (false merge); 0112/0131/0104 split from 0126+0140 (one GT athlete, 4 reels); 0097+0115 still two reels (singleton stage did not merge). Scorecard: FULL 14, >=95% 14, missing 20.4 s, excluded 999, mixed 2, splits 3, published 10 / correct 7. | artifact qualification-diagnostics-q9-paid-02-44121013654 |
| EVD-09-004 | rendered_media | Decoded MP4 viewing (contact sheets at 1.5 fps) of q9-paid-02 reels: 0143+0152 reel (sha256 b7b86f1066e2...) shows two white-top / pink-longboard lookalikes (clip 2 sleeves longer); 0097 reel (70a8d9460ef8...) correct athlete, backlit, foam-only tail; 0115 reel (1708522a574b...) visibly the same athlete as 0097, starts at pop-up (paddle-in missing); 0070+0108 reel (7831b08d9d8a...) correct athlete, clip 2 runs into the GT-excluded shore tail ~20-26 s. | session scratch contact sheets; reels artifact qualification-reels-q9-paid-02-44121013654 |
| EVD-10-001 | isolated_run | Gate A (free, budget 0, production entry point scripts/run_tracked.py). Run 44140263067 @82f8e544: FAILED - the before_qa / after_first_upload fault points sat in the shadowed orchestrator._compile_clusters (production uses pipeline/context_qa_gate.compile_clusters_with_context_qa) and never fired; evaluator keyed inventories by Path.stem. R0/R5 retries no-op and F1 crash clean even there. Run 44148876075 @80fc677b (hooks moved, namespace q10-gate-a2): R0 retry into completed q9-dry-02 = no input, 0 writes, listing identical; F1 after_analysis / F2 before_qa / F3 after_first_upload: exit 97 at the point, 0 processed markers, 0 publishable records, raw unchanged; F3 left 3 complete drafts (3 upload workers); R4 recovery wrote 25 drafts + 24 markers and rewrote every partial key (0 orphans); R5 retry no input, 0 writes; production fingerprint identical. Evaluator corrected after run 2 (substring 'pass' matched qa_passed:false; partial bound 1 -> upload workers) and re-applied to the run's own ledgers: all checks PASS. Limits: at budget 0 QA cannot pass, so a publishable partial is not exercised; draft-name drift on a PAID retry (different model descriptions / next-day date) is not exercised. | artifacts qualification-gate-a-q10-gate-a-44140263067, qualification-gate-a-q10-gate-a2-44148876075; evaluation/qualification/gate_a/ |
| EVD-10-002 | measurement | Gate B diagnoses (private GT boxes, aggregate only). 0094: primary-athlete audit of the q9-paid-02 reel - crop shows 9524ac02 in 195/203 frames, 0 other GT athletes in crop, 0 identity switches; the scorecard's 'mixed' is a time overlap of the 2.0-22.5 s window with d805a9b1's ride (1010-2199 f): the real defect is the end (9.3 s past the GT ride end). 0095: drone frames track 10003 (uncatalogued white-sleeve rider) at centre; GT athlete 6c84aed0 = track 10007 riding the same wave at left, his take GT-excluded (unusable): no tracking/identity defect, owner decision PA-01. | cycle-10 report |
| EVD-10-003 | replay | Gate C replay of FIX-PQ-10-001 on stored runs (scripts/identity_policy_replay.py, GT-v1 ae844a94 digest b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9): q9-paid-02 published 10->8, published_wrong_identity 1->0, published_nonride 2->1, published_correct 7->7, coverage unchanged; 43920602179, q9-dry-02, q9-paid-01 unchanged (no image-evidence passes); 43583126199 NOT_REPLAYABLE (legacy manifest without per-event inputs). | cycle-10 report |
| EVD-10-004 | replay | EXP-10-002 (REJECTED): pre-chosen end-of-ride rule 'board association < 0.5 for 1.5 s after an established ride, +1.0 s margin' replayed on all q9-paid-02 windows against GT: removed 6.2 s of non-include but cut 44.0 s of GT include (0094 11.6 s, 0118 14.7 s, 0074 5.0 s ...). Board detection at stride 5 drops out mid-ride. Not tuned further (24 cases = test set). | cycle-10 report |
| EVD-10-005 | isolated_run | EXP-10-001 q10-paid-01 (run 44166232265 @bf9c9024, $0.206 / cap $0.40, GT-v1 ae844a94 digest b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9). Production fingerprint identical. Pre-registered conditions all met: 0 publishable multi-source reels without operator evidence (5 multi-source reels kept together UNCONFIRMED: 0070+0108, 0094-cluster, 0112-cluster, 0143+0152, 0160+0163); 0 publishable visibly mixed reels (audit: 24/25 shots OK, the one visible mix 0143+0152 withheld); FULL 14, missing 20.4 s, published 5 / correct 4, QA false passes 1 (0095), published wrong identity 0. FIX-PQ-10-003 in situ: the clustering grouped 0097+0115 and 0074+0151, both split on wetsuit_vs_bare_or_swimsuit_conflict, PENDING review requests 758fe7783e9c (0097+0115, GT same athlete) and 7b2a6964427f (0074+0151, GT different). Rendered MP4s: 14 reels, full scaled decode 0 errors / 0 freezes / 0 black; viewed: 0112-cluster (one athlete, 5 clips, correct, withheld), 0160+0163 (one woman, correct, withheld), 0143+0152 (two lookalikes, withheld). Reel SHA-256 prefixes: 0143+0152 30a2aed300b7, 0112-cluster 1ae08503dc19, 0160+0163 3df8c2fb84b4, 0097 7a9280cbde56, 0115 767ecae02f52, 0094-cluster cf6dcb1781f7, 0070+0108 c704b2278366, 0095 ca1813e1e0bd. | artifacts qualification-diagnostics-q10-paid-01-44166232265, qualification-reels-q10-paid-01-44166232265 |

## Blockers

- **BLK-07-001** Durable storage of overlay videos: the overlays need the private GT boxes, which are not in CI and not committed. Options: (a) owner approves writing evidence objects to R2 under an evidence/ prefix, (b) a Supabase read secret in CI. Both need explicit approval.
- **BLK-07-002** Owner decisions: PA-01 (reels for uncatalogued riders), PA-03 (0094 GT end 13.2 s vs standing to ~16 s), PA-07 REVIEW outcome.
- **BLK-07-003** No controlled candidate pipeline run or decoded final render yet. On 2026-11-17 owner authorized a NEW capped experiment campaign of up to $2 incremental total; do not spend without per-run enforcement and attribution. This is not a GO or automatic authorization to publish.
- **BLK-08-001** End-to-end integration (pipeline run -> new EDL -> rendered MP4 -> Review screen) for FIX-PQ-08-003 and later fixes: re-running the same 24 sources needs Run Pipeline with reset=true, which moves PROCESSED->RAW and DELETES current REVIEW drafts (destructive) and lands drafts on the operator Review screen. Requires the owner's explicit approval. Estimated model cost ~$0.5-0.7 (warm cache: logged $0.23 for 43920602179 + identity/singleton calls).
- **BLK-09-001** Paid runs stopped after EXP-09-002. Spent of the $2 campaign: $0.380 (cycle 8) + $0.225 (q9-paid-01) + $0.469 (q9-paid-02) = $1.074; remainder $0.926. run_config.json sets llm_budget_usd_paid 0 and the workflow cap is 0.92; any further paid run needs a fix with a credible safety case and a new pre-registration.
- **BLK-10-001** Paid runs closed after EXP-10-001. Campaign spend $1.280 of $2; remainder $0.720 (run_config paid budget 0, workflow cap 0.72). Owner decisions open: identity review requests 758fe7783e9c (0097+0115) and 7b2a6964427f (0074+0151); PA-01 uncatalogued riders (0095); PA-03 0094 13.2-16 s.

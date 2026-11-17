# Pipeline evidence matrix

Generated from `evaluation/evidence/registry.json` by `scripts/build_evidence_matrix.py` — do not edit by hand.
GT: GT-v1 frozen, dataset ae844a94, digest b31fd9b4…27c9 (unchanged). Runs compared: baseline 43583126199, latest 43920602179.

## Fixes (Gap → root cause → fix → commit → experiment → before/after → evidence → status)

### FIX-PQ-07-001 — Primary-athlete binding reports an inseparable second surfer as ambiguous instead of a silent tie-break

- **Gap:** PA-05 · **Classification:** PIPELINE_DEFECT · **Status:** `REPLAYED`
- **Root cause:** pipeline/perception/runtime._best_primary ranks tracks by a composite with a single timeless crop hint; two surfers crossing at the hint tie and max() picks one silently
- **Fix:** [Code: pipeline/perception/runtime.py::_binding_separability](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/pipeline/perception/runtime.py). _binding_separability: runner-up that is a different body (median IoU < 0.3 over shared frames), co-present for >= 25% of the bound track's window, as close to the hint (<= 0.06, within 0.03) and within 10% on the ranking -> track_binding_status=ambiguous, actor_tracking_status=ambiguous (-> PRIMARY_ACTOR_UNCLEAR via primary_actor_policy). Every event also records track_binding_status / runner_up / evidence.
- **Commit:** 15a732d9dbcfe889cc68d64cc9f8589471e27f9d
- **Experiments:** [EXP-07-001 red/green P1-P8](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/scripts/test_primary_athlete_binding_contract.py) (red 95eb149; green 15a732d), [EXP-07-002 historical binding replay](https://github.com/yotamfried-ux/Video-editing-with-drone/blob/15a732d9dbcfe889cc68d64cc9f8589471e27f9d/evaluation/evidence/binding_replay_2026-11-17.json) (denominator 167 in JSON vs 166 in report: RECONCILE)
- **Before:** P5 bound track 1 with no flag; real windows: n/a
- **After:** P5 ambiguous + PRIMARY_ACTOR_UNCLEAR; P1-P4, P6-P8 unchanged; 0/166 real windows newly blocked
- **Evidence:** EVD-07-004, EVD-07-005
- **Limits:** Crop hints are not exported to diagnostics, so the replay uses the bound track's position at the event middle as the hint (proxy). The co-presence condition was added after seeing 0104 in run 43583126199: development data, not holdout. No real crossing case exists in GT-v1, so the blocking branch is synthetic-only (SIMULATED, not MEDIA_VERIFIED). IMPORTANT: Replay report 0/166 conflicts with committed JSON windows=167. No claim about exact 166/167 denominator until reconciled; the real crossing branch remains synthetic-only. No new rendered MP4 or independent holdout.

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

## Gaps

| ID | Case | Product | Classification | Status | Finding | Next |
|---|---|---|---|---|---|---|
| PA-01 | 0095 | B (exclude segment in a reel) / primary athlete | POLICY_AMBIGUOUS | `MEDIA_VERIFIED` | Two surfers on one wave. GT has one catalogued athlete (6c84aed0, pink board, left), excluded as no_meaningful_action. Both runs render a reel that follows the OTHER rider (white board, centre) for the whole clip with no identity switch; that rider has no GT segment or box. | Use owner-annotated target-athlete identity for GT audit; source-only evidence indicates current reel follows a different, uncatalogued rider. Keep existing GT-v1 exclude and do not edit or mark resolved without adjudication. No automatic publish based on two-surfer presence alone. |
| PA-02 | 0151 | primary athlete / A (coverage) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Three-rider party wave. 11-14 followed a shirtless rider who is not the GT athlete (WRONG_PERSON); 11-16 follows the GT athlete (dark wetsuit). The GT athlete falls at ~5.0-5.5 s (earlier note '6.2-6.9 s' corrected). 11-16 window ends 6.14 s and misses the aftermath to 7.6 s (GT second segment). | The binding in 11-14 followed the analyzer's person choice; not reproducible without the 11-14 hint. Keep 0151 end unchanged (no global extension, per owner). |
| PA-03 | 0094 | B / boundary | GT_DISCREPANCY_SUSPECTED | `MEDIA_VERIFIED` | A's reel (9524ac02) stays on the right surfer (no switch) but runs ~9 s past A's GT end (13.2 s): standing in whitewater to ~16 s, prone/crouched after; from frame 1010 GT's include belongs to d805a9b1, not to A. | Split decision: 13.2-16 s GT end contested, owner must adjudicate; 16-22 s prone whitewater after meaningful action is candidate pipeline tail error. Keep GT-v1 unchanged and create GT-v2 proposal only with consent. |
| PA-04 | 0155 | B (exclude segment in a reel) | PIPELINE_DEFECT | `MEDIA_VERIFIED` | Takeoff lying/kneeling, crouched, drops prone ~6.5 s: no standing ride. GT exclude is correct. 11-16 renders all 7.8 s inside A's (9524ac02) reel; tracking follows the right person. | Needs a stand-up evidence requirement or a pinned analysis cache; any detector change needs a held-out set (no fitted thresholds). |
| PA-05 | synthetic | primary athlete | PIPELINE_DEFECT | `REPLAYED` | Crossing surfers with an inseparable hint were bound by tie-break without a flag. | Red/green test passed on FIX-PQ-07-001@15a732d9; replay count conflict 166 vs 167 must be reconciled; no decoded new render or real crossing holdout. EVD-07-004/005 only. |
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
| EVD-07-005 | replay | Historic binding replay across seven runs; zero reported newly ambiguous windows, but denominators conflict (artifact windows=167 vs report 166) and crop hints are proxied. Not a production or holdout proof. | evaluation/evidence/binding_replay_2026-11-17.json |
| EVD-07-006 | visual_identity | GT-box crops side by side: 0143 vs 0152 and 0097 vs 0115 | derived from EVD-07-001 (session scratch); sent to the owner |

## Blockers

- **BLK-07-001** Durable storage of overlay videos: the overlays need the private GT boxes, which are not in CI and not committed. Options: (a) owner approves writing evidence objects to R2 under an evidence/ prefix, (b) a Supabase read secret in CI. Both need explicit approval.
- **BLK-07-002** Owner decisions: PA-01 (reels for uncatalogued riders), PA-03 (0094 GT end 13.2 s vs standing to ~16 s), PA-07 REVIEW outcome.
- **BLK-07-003** No controlled candidate pipeline run or decoded final render yet. On 2026-11-17 owner authorized a NEW capped experiment campaign of up to $2 incremental total; do not spend without per-run enforcement and attribution. This is not a GO or automatic authorization to publish.

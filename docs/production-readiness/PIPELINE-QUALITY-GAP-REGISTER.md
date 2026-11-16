# SportReel — Pipeline quality gap register and 20-run regression investigation

**Audit date:** 2026-11-16 UTC. **GitHub main baseline:** 59c84864b2e7f2242f358bde9923c621575ce7c5.  
**State:** OPEN / NOT_READY. This is a **read-only historical investigation and remediation register**, not evidence that the media defects have been fixed.  
**Scope:** source-event inference, tracking, cross-source athlete grouping, action boundaries, final QA, qualification and output vs frozen Ground Truth.  
**Separate app register:** [MOBILE-APP-GAP-REGISTER.md](./MOBILE-APP-GAP-REGISTER.md). Do not mix application release/payment tasks with pipeline quality tasks.  
**Key evidence:** GitHub Actions logs and artifact metadata for Run Pipeline; the owner's 2026-11-16 HTML discrepancy report and six-page DOCX repair plan; provisional, unmerged [PR #391 GT regression analysis](https://github.com/yotamfried-ux/Video-editing-with-drone/pull/391) and its measurement script.

## 1. Evidence and interpretation: what can actually be concluded

**Independently checked in this audit:** exact 20 most recent workflow_dispatch runs named Run Pipeline, their statuses, SHAs, jobs, and diagnostic artifact presence; logs of all eight completed successful jobs; source code on main; #391 code and test changes; Engineering-OS knowledge library; upstream documentation for relevant CV tools. Logs establish **release-gate counts**, not true visual quality. Existing GT scores in #391 are *independently inspected source reports*, but this audit did **not** download/parse their binary ZIP artifacts or watch any footage. Those GT numbers are therefore **REPORTED_GT_METRIC / NOT_INDEPENDENTLY_REPLAYED** until verified with the exact artifacts and approved annotations.

**Do not equate:** workflow success, artistically good video, QA model PASS, gate publishable, one actual human-approved athlete, and frozen-GT correspondence. Denominators differ: GT-v1 is reported as **24 annotated sources / 24 physical rides / 13 athletes**; the processed batch is described as **29 file markers** with additional unannotated sources; the pipeline inferred **13–14 reel groups** depending on run. A 5/14 gate count is not the same metric as 4/13 GT-correct published athletes.

**Cross-report discrepancies to reconcile:** HTML headline counts **10** starts/ends shifted more than 1 second; the DOCX introduction says **7**. Both mention a 29-file processing batch, although GT-v1 has 24 annotated sources. The GT checker uses 50% temporal coverage to mark a ride covered: its 24/24 is **not** 24/24 fully preserved rides. Freeze source hashes, GT digest, actual frame boundaries and metric definitions before asserting zero error.

### 1.1 Method for selecting the 20

Query: GitHub repository Actions runs, event=workflow_dispatch, filter displayed name prefix 'Run Pipeline', order by creation date descending, take 20. Period **2026-11-12 10:48:59 UTC to 2026-11-16 17:39:06 UTC**. Exactly **8 successful** with pipeline-diagnostics artifact; **12 cancelled**, with no final diagnostic artifacts. Do not treat cancelled runs as completed media-quality observations. A cancelled job may have written partial state; its **database-side effects were not audited here**, and lack of a ZIP is not proof of no side effects.

| Order | Run | UTC date | Commit prefix | GitHub result | Diagnostic ZIP | Final gate |
|---:|---:|---|---|---|---|---|
| 1 | [43920602179](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43920602179) | 16 Nov 17:39 | a11b4012 | success | 14255932785 | 5/14 |
| 2 | [43920015502](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43920015502) | 16 Nov 17:35 | a11b4012 | cancelled | none | n/a |
| 3 | [43911425421](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43911425421) | 16 Nov 16:47 | e26418af | cancelled | none | n/a |
| 4 | [43910230097](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43910230097) | 16 Nov 16:41 | e26418af | cancelled | none | n/a |
| 5 | [43906416932](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43906416932) | 16 Nov 16:20 | e26418af | cancelled | none | n/a |
| 6 | [43897129968](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43897129968) | 16 Nov 15:30 | e26418af | cancelled | none | n/a |
| 7 | [43816344303](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43816344303) | 16 Nov 06:22 | 2b7d4cf7 | success | 14204326687 | 10/14 |
| 8 | [43725044948](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43725044948) | 15 Nov 14:33 | 185b6fd5 | success | 14167525908 | 10/14 |
| 9 | [43712059697](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43712059697) | 15 Nov 12:05 | 9a03610a | cancelled | none | n/a |
| 10 | [43710581656](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43710581656) | 15 Nov 11:47 | 9a03610a | success | 14162886161 | 10/14 |
| 11 | [43690351380](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43690351380) | 15 Nov 07:31 | 825bae48 | cancelled | none | n/a |
| 12 | [43688587086](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43688587086) | 15 Nov 07:08 | 825bae48 | cancelled | none | n/a |
| 13 | [43639236069](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43639236069) | 14 Nov 20:46 | 7d6b544b | cancelled | none | n/a |
| 14 | [43610023497](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43610023497) | 14 Nov 15:24 | 7d6b544b | cancelled | none | n/a |
| 15 | [43608059893](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43608059893) | 14 Nov 15:03 | 7d6b544b | cancelled | none | n/a |
| 16 | [43587564991](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43587564991) | 14 Nov 10:55 | 7d6b544b | cancelled | none | n/a |
| 17 | [43583126199](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43583126199) | 14 Nov 09:59 | 7d6b544b | success | 14110304094 | 12/13 |
| 18 | [43397405813](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43397405813) | 13 Nov 08:58 | 6362b1b6 | success | 14026361543 | 11/13 |
| 19 | [43303438106](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43303438106) | 12 Nov 20:45 | 041eadb3 | success | 13989725058 | 13/14 |
| 20 | [43203677423](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43203677423) | 12 Nov 10:48 | 17b5fe46 | success | 13939757629 | 12/13 |

### 1.2 Completed-run comparison — independently read from job logs

| Run | Passed publishability gate | Candidate / selected actions | LLM cache restored | Approx model calls/cost in logged accounting | GT-correct published as reported by #391 |
|---|---:|---:|---|---|---:|
| 43203677423 | 12/13 | 29 / 24 | yes, from 43079298706 | 19 / $0.2077 | 7 |
| 43303438106 | 13/14 | 33 / 24 | **no** (cold) | 50 / $1.6478 | 9 |
| 43397405813 | 11/13 | 33 / 24 | yes | 17 / $0.2288 | 8 |
| **43583126199** | **12/13** | **33 / 24** | yes | 18 / $0.2178 | **9 (best measured baseline)** |
| 43710581656 | 10/14 | 32 / 25 | **no** (cold) | 48 / $1.6086 | 7 |
| 43725044948 | 10/14 | 32 / 25 | yes | 18 / $0.2413 | **not evaluated in #391 table** |
| 43816344303 | 10/14 | 32 / 25 | yes | 20 / $0.2409 | 7 |
| **43920602179** | **5/14** | **32 / 25** | yes | 20 / $0.2297 | **4** |

Caveats: costs are model-cost accounting as logged, not total infrastructure spend. GT-correct counts are from unmerged #391's historical report, not independently recomputed here. The denominator 14 is the pipeline's inferred groups, not the 13 GT athletes.

**Quality drop is two different changes:** From 14 Nov to 15 Nov, the detected grouping and selected action set changed on a **cold Gemini reanalysis** (24 -> 25 selected actions, 13 -> 14 groups, new 0155 candidate, 0097/0115 false split reported). From 16 Nov morning to evening, **the selected actions stayed 25/25**, but publishability dropped 10/14 -> 5/14 as stricter code/evidence requirements blocked five additional groups. Correct publication reported by the GT checker fell from 9 (14 Nov) to 7 (15 Nov) to 4 (latest). **Reverting gates to regain 12 published reels is not a valid quality fix.**

### 1.3 Additional outside-20 history (context only)

The preliminary #391 report also measured runs **42891165218** (10 Nov, 4 GT-correct of 7 published) and **43013005072** (11 Nov, 6 GT-correct of 10 published). They are **not** among the 20 most recent selected above and are kept separate from that sample. Nine total runs were compared by #391; one of the newest eight successful runs, 43725044948, was not present in its comparative table.

## 2. Root-cause assessment — confidence and first failing layer

**CONFIRMED in logs:** cold cache on 43710581656 (no restore; 48 calls); subsequent cache reuse; gate 12/13 on 43583126199 vs 5/14 on 43920602179; 44 withheld diagnostic findings on the latest run versus 6 on 43583126199; five latest parts blocked by unconfirmed group identity, in addition to track/tail/final-QA blocks. On the latest run, the already selected 25 events and 14 manifest rows stayed unchanged compared with 43816344303.

**CODE-CONFIRMED / NOT YET REAL-RUN-VERIFIED:** #391 patch reveals that identity_evidence.member_key preferred run-local _clip_index while verification recorded membership, whereas the later stripped release representation relied on source path; the fix reverses preference. Reproducing this transition is covered by #391 tests, but #391 is **OPEN DRAFT and not merged** at audit time. Its proposed 2.0 -> 2.5 sec global track-gap relaxation, and permitting short tails after lost tracking, require cross-actor adversarial validation; do not approve solely from GT examples.

**HIGH-CONFIDENCE HYPOTHESIS supported by uploaded comparison and #391 analysis:** the cold LLM analysis altered video interpretation, selecting 0155 as a ride (was no_complete_action), splitting 0097/0115 on changed descriptions and changing 0151 boundaries. The log proves the cold cache; exact changed LLM answers should be diffed using raw per-source response keys and model/prompt versions before declaring this fully verified.

**PERSISTENT UNDERLYING PRODUCT ERRORS:** 0095 appears to be an SUP/standing paddleboard candidate, while the owner's surfing GT excludes this source as **no eligible surf ride**; 0155 failed takeoff; 0108 tail beyond marked 6.8s end; 0094 A3 interval encroaches on A4; 0143+0152 incorrectly grouped; 0097+0115 incorrectly separated; multiple leading/trailing windows missing marked action. Older permissive gates exposed these errors rather than fixing them.

**Important methodological correction:** A successful GT score generated by scripts/gt_product_check.py is not visual proof that the cropped athlete remains centered or continuous in every rendered frame; it relies on selected windows, source SHA, string-form action_lineage and overlap attribution. An independent reel/frame review is still required.

## 3. Gap register (append-only IDs)

| ID | P | State | Concrete gap; known examples | First relevant modules | Required exit evidence |
|---|---|---|---|---|---|
| PQ-01 | P0 | CONFIRMED | Publish invalid/excluded surfing content (0095 SUP/no eligible surf ride, 0155 failed takeoff, 0108 tail) | output_qualification.classify_action, performance_reel_policy, analyzer | Video-based positive surf-ride verifier; zero selected excluded content; valid rides retained |
| PQ-02 | P0 | CONFIRMED | Mix athletes across shots/sources (0143+0152, 0094 A3/A4) | stages/identity.py, identity_decision_engine.py, identity_failsafe.py | No mixed-actor reel in GT holdout; pairwise visual evidence, ambiguous cases held |
| PQ-03 | P0 | CONFIRMED | One GT athlete split across reels (0097+0115; A4 segment split from 0094) | stages/identity.py, subject/track association | One reel per verified athlete without merging different athletes |
| PQ-04 | P0 | CONFIRMED | Tracking fragmentation, misplaced PRIMARY_ACTOR_UNCLEAR, and unsafe handoffs (0115, 0094) | subject_gate_policy._continuity_ratio; missed_moment_rescue | Tracklet stitching with motion+appearance+negative constraints; ID switches, HOTA/IDF1, two-actor tests |
| PQ-05 | P0 | CONFIRMED | Incomplete catch/paddle start (0115 4.4s; 0094 A4 10.1s; 0104 2.5s; 0162 1.5s; 0142 1.2s; 0152 1.1s) | complete_action_window_policy.extend_to_setup, analyzer, window_refinement | Catch-start validated by observed source frames; <=0.5s per human-adjudicated boundary or explicit justified exception |
| PQ-06 | P0 | CONFIRMED | Invalid/early/late endings (0108 +2.4s, 0151 -1.5s, 0094 A3 +9.3s, 0070 unlabeled inter-ride gap) | extend_to_outcome, extend_to_recording_end, output_qualification.action_interval | No prohibited tail or wrong actor; verified ride outcome retained; clear policy on 0070 |
| PQ-07 | P0 | CONFIRMED | GT checker can report 24/24 rides while eight are partially truncated; 50% coverage qualifies as 'covered' | PR #391 scripts/gt_product_check.py | Distinct ANY / >=50% / >=95% / FULL-ANNOTATED coverage and missing-seconds per ride; no false 'complete' label |
| PQ-08 | P0 | CONFIRMED | Regression gates in #391 omit excluded_frames_selected, mean_start_error_frames, mean_end_error_frames and withheld-correct count | PR #391 REGRESSION_KEYS / compare() | Every critical metric guarded, null/missing fields fail closed, baseline and holdout both checked, independent test |
| PQ-09 | P0 | CONFIRMED | Gemini analysis can materially change after ephemeral GitHub Actions cache loss | integrations/llm_cache.py, pipeline-run.yml | Content-addressed immutable response and detector sidecars in existing storage, replay without paid calls, A/B isolate code/model/cached input |
| PQ-10 | P0 | CONFIRMED | Identity evidence recorded on run-local _clip_index but checked after stripping internal fields | identity_evidence.member_key, stages/identity._strip_internal_fields; PR #391 fix unmerged | Same verifier evidence passes before/after production transform; source SHA prevents basename collision |
| PQ-11 | P1 | CONFIRMED | Qualification gates may withhold GT-correct clips for weak continuity/tail evidence; unsafe to simply relax numerical thresholds | output_qualification MAX_TRACK_GAP_SEC; PR #391 | Golden positives + adversarial negatives for gaps 1.9/2.09/2.3/2.5/3.6s and tail 0-3s; no wrong actor admitted |
| PQ-12 | P1 | NOT_VERIFIED | Final QA and publishable status do not prove editorial/Ground Truth correctness | final QA, publishable_reel_manifest, GT checker | Independent side-by-side media review by source frame, QA and source SHA; product verdict separate from workflow success |
| PQ-13 | P1 | CONFIRMED | Benchmark coverage is only 24 GT sources out of 29 batch markers; some count/metric definitions disagree between reports | evaluation/ground_truth, GT report | Reconciled inventory/hashes/GT revisions, exact source cohort and labelled coverage, no invented labels |
| PQ-14 | P1 | INVESTIGATE | 12 of newest 20 runs cancelled; no diagnostic ZIPs, effects/causes of cancellations not established | GitHub Actions concurrency, dispatch and run ledger | Reason for cancellations, partial writes, cost and cleanup reconciled; distinguish user cancellations from automated supersession |
| PQ-15 | P1 | NOT_VERIFIED | New PR #391 has synthetic tests and proposed GT checker but not a final real-video release gate | PR #391 branch, GT Product Check workflow | PR review, benchmark test, merged SHA + controlled real video run + actual media QA |
| PQ-16 | P1 | INVESTIGATE | Reader cannot fully trust GT-correct metric when part-level publishable differs from reel-level action_lineage; overlap attributes on relative time | PR #391 gt_product_check.evaluate | Per-part event UID/source SHA/frame attribution; missing lineage blocks evaluator, overlapping interval counterexample tests |
| PQ-17 | P1 | NOT_VERIFIED | Same athlete across videos vs lookalikes; one thumbnail per appearance may be insufficient | track_bbox_sheet, identity_failsafe | 4-6 source-frame crops per appearance, calibrated pairwise confusion matrix with human adjudications, zero unsafe merges on held-out clips |

New gaps must use PQ-18 onward and retain original evidence rather than deleting earlier findings.

## 4. Highest-leverage fixes in a safe order

1. **Make measurement trustworthy before tuning.** Complete read-only GT evaluator; add actual missing-seconds coverage, excluded-frame regression, actor handoff and boundary quantiles (mean alone hides worst 0094 error). Verify run 43725044948 (currently missing GT score). Keep GT out of inference and protect frozen test labels. Explicitly distinguish 29 input items from 24 GT-labelled sources.
2. **Freeze the model/detection inputs for A/B.** Archive content-addressed Gemini raw response, exact prompt, model/version/config, detector + track sidecars, source hashes, codec/fps, run SHA in existing authorized storage. Use a read-only, versioned offline replay fixture. GitHub Actions cache can accelerate but must not be the sole durable evidence source. Do not change production storage/migrations without approval.
3. **Fix identity evidence lineage and calibrate identity.** Test #391 _clip_index-to-path fix, collision-resistant SHA+person key, 4-6 contact sheet crop positions per appearance, pairwise NO_MATCH constraints; never trust text similarity to merge or text contradiction alone to prevent image comparison. Use blind train/validation/test and inspect 0143+0152 and 0097+0115.
4. **Stitch tracklets with evidence, not arbitrary longer thresholds.** Use current tracker continuation tools and introduce motion/spatial/appearance likelihood plus contradiction constraints. Track source-local lineages, start/end in frames, ID switch transitions; disallow A3->A4 handoff in 0094. Re-evaluate PRIMARY_ACTOR_UNCLEAR on 0115/A3/A5. Test counterexamples before changing MAX_TRACK_GAP_SEC.
5. **Verify actual surfing action.** Reject SUP/failed takeoffs from surfing-only selections with a positive surf-action proof, not just an analyzer score+box activity. A narrow second review on disputed clips may be a cost-controlled option, calibrated against independently viewed GT. Do not wrongly suppress a real ride.
6. **Repair actor-safe temporal boundaries.** Make catch_start and outcome_end measured/verified source-frame events, preserve early paddle-in where approved, avoid unjustified recording-end extension, split two separate rides/athletes. Reconcile product choice about 0070 before coding its transition.
7. **Run frozen replay and adversarial regression first.** For every change: same source/model/sidecars, GT train -> validation -> sealed test; compare with best run (43583126199) on BOTH correct publishable and wrong publishable. A change is not an improvement if it raises one metric by weakening safety.
8. **One authorized controlled real-video run.** Only after all code-verifiable gates are green, request owner approval for any paid pipeline run. Inspect rendered media, overlays and QA, not just diagnostic JSON. No automatic approve/publish of disputed reels.

**Measurement targets** (only for fully adjudicated GT cases; mark unavailable others): zero confirmed wrong-athlete merged outputs; zero excluded frames in publishable reels; zero invalid non-surf rides; full valid ride coverage or evidence-backed source limitation; start/end deviation <=0.5s per annotated ride; every eligible one reel or explicit supported rejection; no new false-positive stop on valid holdouts. Do not expect a perfect score on unreviewed future footage, and never silently degrade acceptance criteria.

## 5. Engineering-OS reuse map — reuse code only where it fits

The user's [Engineering-OS](https://github.com/yotamfried-ux/Engineering-OS) is a knowledge **library**, not a runtime. Inspected:
- [CV tracking guide](https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/architecture-guides/cv/tracking.md) — Kalman association, appearance-based re-identification and IDF1/HOTA; relevant to PQ-02/03/04.
- [Video analytics guide](https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/architecture-guides/cv/video-analytics.md) — detector -> tracker -> event logic -> product evidence and monitoring.
- [Computer vision template](https://github.com/yotamfried-ux/Engineering-OS/blob/main/templates/computer-vision/README.md) — versioned train/validation/test, data/ground-truth tools, regression and video test architecture.
- [Supervision reference](https://github.com/yotamfried-ux/Engineering-OS/blob/main/external-systems/supervision/README.md) — object detections, bbox overlays and review evidence.
- [SAM3 research note](https://github.com/yotamfried-ux/Engineering-OS/blob/main/capability-registry/discoveries/sam3-sports-vision.md) — optional GPU-assisted segmentation, *not* a rule verifier.
- [OpenMontage reference](https://github.com/yotamfried-ux/Engineering-OS/blob/main/external-skills/openmontage/README.md) — approval checkpoints, render proof and artifact provenance.
- [Testing fast path](https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/FAST-PATH.md) — cheapest falsifiable unit/contract/integration/video test.

### Concrete upstream reuse opportunities (not yet integrated)

| Candidate | Verified code/docs and reusable unit | SportReel insertion point | Cautions / decision |
|---|---|---|---|
| **Ultralytics BoT-SORT / ByteTrack / OC-SORT** | [BoT-SORT configuration](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/trackers/botsort.yaml), [official tracker documentation](https://docs.ultralytics.com/modes/track/) | Existing YOLO tracker setup and PQ-04 tracklet association; test gmc_method, track_buffer, appearance, confidence across 0094/0115 | Prefer configuration/profile A/B before adding a second tracker. Current project uses ultralytics>=8.3.0; upstream and deployed versions may differ. Upstream uses **AGPL-3.0/commercial licensing**: review product use before copying/vendoring code. |
| **roboflow/supervision** | [Project](https://github.com/roboflow/supervision), [docs](https://supervision.roboflow.com/), bounding box, trace/mask annotators and Detections data model | Existing review overlay generation, actor switch contact sheets, PQ-12/17 visual comparison | **Already installed** as supervision>=0.29,<0.30. Keep current API or consciously upgrade: newer upstream removed its built-in ByteTrack wrapper in 0.31; don't paste new tracker APIs into pinned 0.29 without verification. License MIT subject to current upstream check. |
| **ByteTrack** | [Official repository](https://github.com/ifzhang/ByteTrack), [research paper](https://arxiv.org/abs/2110.06864) | Dual-stage low-confidence association as design/reference for weak detections | Does not by itself solve cross-camera appearance or distinguish two same-time surfers; first assess existing BoT-SORT support. |
| **DeepSORT** | [Reference implementation](https://github.com/nwojke/deep_sort) | Appearance evidence to reconnect validated fragments | Longer occlusions may benefit but lookalikes can still merge; benchmark cost, license and held-out identity error before adoption. |
| **SAM 2 video predictor** | [SAM2 video predictor code](https://github.com/facebookresearch/sam2/blob/main/sam2/sam2_video_predictor.py) | Optional read-only mask propagation in a few difficult 0094/0151/0143/0152 frames | Research-only candidate unless license, memory, GPU expense and actual accuracy measured. A mask is not a surf eligibility or athlete identity verdict. |
| **OpenMontage** | [Engineering-OS entry](https://github.com/yotamfried-ux/Engineering-OS/blob/main/external-skills/openmontage/README.md) and upstream | Reuse pattern: human approval checkpoint, FFprobe and sampled-frame post-render checks; tie into publishability evidence | Adapt proven patterns, not a wholesale video-agent rewrite. Inspect actual upstream license before copying code. |
| **FiftyOne / CVAT** | [CV template](https://github.com/yotamfried-ux/Engineering-OS/blob/main/templates/computer-vision/README.md) | Optional local read-only visualization to review error slices, false merge and start/end frames | Prefer existing Annotation Studio as ground truth. Export only approved compressed proxies, do not migrate or duplicate GT. |

**Code snippets to prototype (not production changes):**
- Use the existing Ultralytics package: YOLO(...).track(source=proxy_path, tracker='botsort.yaml', persist=True), with version-compatible tracker config; collect source-frame track_id, box and confidence alongside each frame.
- Use the project's pinned supervision 0.29 and its Detections/BoxAnnotator/TraceAnnotator to draw overlays, and retain raw, attributed track evidence; do not invent a new tracker wrapper.
- Use existing integrations/llm_cache.make_key(kind, media_sha256, prompt, model, version, extra) to address immutable replay blobs; change *durability*, not the key semantics, and store exact response hash+provenance.

**Avoid copy-paste errors:** upstream documentation can change; check actual installed versions and licenses, prevent GT leakage into production inference, measure speed and compatibility on representative drone footage, and do not add new paid models or services without approval.

## 6. Acceptance tests and evidence ledger to create

| Gate | Focused cases and assertable result | Evidence |
|---|---|---|
| PQ-G1 — GT metric integrity | 50% selected ride not COMPLETE; excluded +1 frame fails; boundary +0.6s fails; missing field fails; overlap may not double count coverage; part-level publishable verified | Red/green evaluator unit fixtures, adversarial real source annotation |
| PQ-G2 — Same input replay | Same SHA, source, Gemini raw output, tracker sidecar -> same pre-QA identity/window/event decisions; compare code revisions without rerunning paid models | Versioned replay manifest and diff |
| PQ-G3 — Positive/negative identity | 0143 != 0152, 0097 == 0115, 0094 A3 != A4; simultaneous lookalikes and same-name different-hash sources; exact per-pair evidence | Blinded image sheets + independently reviewed labels |
| PQ-G4 — Action class | 0095 and 0155 rejected for *surfing*, other real short/long rides retained | Video-level ride/not-ride confusion matrix, no hidden GT inference |
| PQ-G5 — Boundaries | 0115 start 0.1; 0094 A4 start 16.9; 0104 start 0; 0151 end 7.6; 0108 end 6.8, subject to source-frame validation | Frame-exact overlays, EDL and rendered 4K/post-proxy review |
| PQ-G6 — Correct release | Exactly one valid personal reel per GT athlete or evidence-backed block; no unapproved content; no wrong-actor clip | Final publishability manifest, actual output and independently recorded acceptance |
| PQ-G7 — No regression | Compare candidate vs both frozen 14 Nov baseline and last run: no worsening in excluded frames, time errors, wrong identity, split, correct publishable, valid-action recall | Automated CI report plus protected holdout |
| PQ-G8 — Operations | Track canceled jobs, possible partial state, idempotent reruns, checksum and cost | GitHub job timeline, storage/DB read-only state, recovery simulation |

**Do not claim all gates PASS from #391 CI.** The GT Product Check workflow is proposed on unmerged #391; real production routing and new candidate media have not been independently certified.

## 7. Open owner choices (do not silently invent product policy)

1. Should the clip include the approach/paddling catch from the GT annotation, or is a shorter lead-in acceptable? This determines a correct opening boundary, not merely a technical tolerance.
2. Source 0070 contains two physical rides by A1 with an unlabelled gap. Should the final reel have two segments or a continuous shot? Require explicit decision before altering cut/merge behavior.
3. Can a second independent recording day be annotated as an unseen holdout? The 24 annotated sources are a limited cohort.
4. Is a stronger/paid image or narrow action verifier permitted, and with what budget cap? Start with zero-added-cost replays and existing video proxies.
5. Confirm the real 29-file batch manifest, the 24 frozen GT source SHA-256s, and how the other five should be evaluated; do not interpret them as verified negatives without review.

## 8. Next change process and user-reported gaps

For every added issue: assign PQ-18 onward, timestamp, reproducible symptom, first failing pipeline stage, affected run IDs/source hash/GT revision, confidence, actual impact, prior vs current source outcome, minimal fix, red/green test, real-video acceptance, PR and exact SHA. Treat reports from other agents as hypotheses until independently corroborated. Never weaken QA just to increase the number of green reels.

**Owner-controlled:** no full paid run, cloud writes, GT modifications, production policy relaxation, PR #391 merge or publish of disputed media without explicit authorization. A documentation-only merge of this register does not approve those operations.

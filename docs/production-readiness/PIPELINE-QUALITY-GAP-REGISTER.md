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
## 9. Expanded systemic gap coverage and end-to-end release plan (2026-11-16 follow-up)

**Review basis:** GitHub \`main\` at \`1bff18d36b73cb70d8e08ff3ed42d6d3e36dbfc2\`; [draft PR #391](https://github.com/yotamfried-ux/Video-editing-with-drone/pull/391) at \`479169fa590d87180db1f2dd547962c3e4f5fa29\`; the *code and schema* of its proposed frozen GT-v1 file (not a separate visual validation), and the Engineering-OS references below. **This is a research and qualification plan, not a claim of fixed video defects.** This follow-up did not download/play rendered footage, verify R2 source files independently, run paid inference, edit GT, or operate Google Play/Grow.

### 9.1 Newly established facts and limits

- **Frozen-GT schema inspection:** PR #391 contains 24 source SHA-256 members, **13 distinct athlete IDs, 42 include segments, 3 exclude segments, 24 reviewed ranges**. Applying the PR's exact \`_rides()\` heuristic (same athlete and <=3-frame gap) yields **24 putative physical rides**, not 42 independent waves. One annotated source contains segments from two different athletes; athletes appear across as many as five sources. The count of 24 depends on the heuristic, not on an explicit adjudicated physical \`ride_id\`.
- **One-reel policy exists but is downstream:** \`pipeline/performance_reel_policy.py::_patch_editor\` calls \`partition_complete_performance_reels(..., single_part=_one_reel_per_athlete())\`; \`SPORTREEL_ONE_REEL_PER_ATHLETE\` defaults to enabled. This only packs events **inside each already-produced athlete cluster**. If \`stages/identity.py\` creates two clusters for one real athlete, a local \`single_part\` flag cannot guarantee one product reel overall. Confirm with the final manifest, not just the partitioner.
- **A deduplication guard already exists:** \`pipeline/final_duplicate_guard.py::remove_duplicate_events\` and its editor patch. Measure its event-fingerprint/overlap behavior and source provenance before adding a new deduper. It can remove duplicate candidate events, but is not proof of global identity reconciliation, physically distinct waves, or duplicate delivered files.
- **Critical proposed evaluator failure modes, confirmed from PR #391 source:** \`RIDE_COVERAGE=0.5\` means half a ride can be marked \`rides_covered\`; \`REGRESSION_KEYS\` omits \`excluded_frames_selected\`, boundary errors and \`correct_reels_withheld\`; \`compare()\` *continues* on missing baseline/current metric, so an incomplete report can pass; \`covered_frames += overlap\` can double count overlapping selected windows. Reel attribution is based on string \`action_lineage\`, filename lookup and time-window overlap, not a verified per-rendered-frame source/actor ledger. These are changes required **before** relying on an automatic green GT gate.
- **Identity evidence still has a compatibility gap on main:** \`identity_evidence.member_key\` prefers the run-local \`_clip_index\`, but that field can be stripped before release qualification. Draft #391 changes the preference to basename, but basename alone is not collision-resistant; require a source content digest plus actor/appearance ID and tests before accepting the long-term design. \`stamp()\` records group-wide cross-source MATCH edges; ensure those reflect actual examined evidence, never synthesize positive pairwise verdicts without adequate member-level proof.
- **Quality vs publishability remain separate:** The PR #391 workflow's successful **pull_request contract job** demonstrates test execution on fixtures; it does not download the named production-run diagnostics on PR events, render a fresh reel, or certify cropped subject continuity. The unmerged historical comparison is useful *provisional* evidence only.

### 9.2 New append-only gaps — PQ-18 onward

| ID | Priority | State as of 16 Nov | Gap and first responsible stage | Required independent exit evidence |
|---|---|---|---|---|
| **PQ-18** | **P0** | CODE-CONFIRMED DESIGN LIMIT / REAL OUTCOME OPEN | **Global one-athlete/one-reel invariant:** pre-editor athlete-cluster splits bypass local \`single_part\`, yielding two separate reels for the same athlete/waves. \`stages/identity\` -> \`athlete_canonicalization\` -> \`performance_reel_policy\` -> final manifest. | GT athlete ID -> all unique eligible rides -> exactly one approved primary reel (unless an explicit, documented product exception); no false merges. Test 0097+0115 and another multiple-wave athlete. |
| **PQ-19** | **P0** | CODE-CONFIRMED EVALUATION LIMIT | **Physical wave vs maneuver/segment:** the PR checker derives rides by merging same-athlete \`include\` segments within a 3-frame gap; an explicit stable \`ride_id\` and reviewed inter-ride policy are absent from this evaluator. \`gt_product_check._rides\`, event grouping and \`final_duplicate_guard\`. | Human-adjudicated ride IDs and wave counts in a *separately versioned proposal* (never silently modify GT-v1); one physical ride appears once, two real rides remain two events but share one athlete reel. Source 0070 is a required case. |
| **PQ-20** | **P0** | NOT_VERIFIED | **Duplicate or dropped content across representations:** detection candidates, selected events, editor parts, render segments, manifest rows, delivery revisions may duplicate one wave or omit another. | Source SHA + ride UID + athlete UID + event UID + exact frame ranges survive all stages; bijective reconciliation for eligible rides; assert no duplicate source interval/ride and no silent drop. Inspect \`final_duplicate_guard\`, \`publishable_reel_policy\`, delivered artifacts. |
| **PQ-21** | **P0** | CODE-CONFIRMED EVALUATOR LIMIT | **Actual completeness and no double counting:** 50% criterion, overlap accumulation, missing-metric skip, omitted excluded/boundary/withheld regression checks in unmerged PR #391. | Per-frame interval-union coverage, explicit ANY/50/95/FULL, max and p95 start/end error, excluded frames, valid withheld, precision/recall and negative controls; required nulls/error schemas fail the CI gate. |
| **PQ-22** | **P0** | NOT_VERIFIED | **What got rendered != what manifest claims:** EDL, transitions, retiming, crop and final encoding may change actor centering, temporal boundaries or actual inclusion. | Per-output-part evidence map from output video frame -> source SHA, source frame, actor, ride; decode/ffprobe/overlay spot-check and independent visual QA of all ambiguous/held/released positives. Verify 0094, 0108, 0115, 0151. |
| **PQ-23** | **P0** | CODE-CONFIRMED DESIGN RISK | **Identity evidence may be attached to the wrong member or rely on filename collisions and ungrounded pairwise edges.** Existing \`identity_evidence.py\` / PR #391. | Collision-resistant member keys, before/after strip contract, mismatch/occlusion/lookalike adversarial sets, all asserted MATCH edges backed by tested visual evidence, zero unsafe merges in adjudicated holdout. |
| **PQ-24** | **P1** | NOT_VERIFIED | **Dataset version, leakage and holdout reliability:** 24 labeled sources vs 29 file markers, old annotations not guaranteed to cover future filming conditions or sports. | Immutable source digests, reviewer decision lineage, explicit reviewed/unreviewed/unlabeled separation, actor and wave held-out splits (avoid near-duplicate leakage), unseen capture-day cohort, blinded adjudication. |
| **PQ-25** | **P1** | NOT_VERIFIED | **Retry/cancellation correctness:** superseded runs and reprocessing may leave partial selection, manifest, upload or publish state. | Idempotent run/athlete/ride/output revision keys, atomic publication, cleanup/reconciliation ledger, concurrent/retried/cancelled workflows and 0 missing/duplicate final assets, after independent DB/storage inspection. |
| **PQ-26** | **P0** | NOT_VERIFIED | **End-to-end publish safety:** source action eligible, source actor correct, cluster proven, rendered clip matches evidence, operator approved and delivery completed must all hold together. | Typed per-reel \`NOT_READY / REVIEW / QUALIFIED / APPROVED / DELIVERED\` state and signed evidence links; veto on unknown lineage; attempt to bypass any stage must fail. Cross-link APP-006. |
| **PQ-27** | **P1** | NOT_VERIFIED | **Production performance and observability:** runtime/cost/per-event latency, retries, cache lineage, 4K/post-proxy rendering, model changes; no proven SLO under realistic load. | Frozen test cohort and controlled load/recovery measurements: p50/p95 duration, expense per correctly delivered reel, failure/cancellation/repair rate, infrastructure ceilings, alert and rollback exercise. Compare with 30-minute product aspiration without promising it. |
| **PQ-28** | **P0 release dependency** | POLICY / DEVICE NOT VERIFIED | **Mobile payment/store release dependency:** even a correct reel cannot be sold via a non-compliant Play checkout or unreliable Android delivery. | [APP-001..APP-020](./MOBILE-APP-GAP-REGISTER.md) must be qualified, including Play policy, production AAB, Android API 36 target eligibility, account deletion, privacy/Data safety, Grow sandbox, entitlement and refund. Keep implementation in app register, not this pipeline register. |
| **PQ-29** | **P1** | NOT_VERIFIED | **Commercial-media rights and safe distribution:** filming permissions/consents where needed, athlete/privacy requests, licensed audio, replay/delete/retention rules, footage access and watermark leakage. | Documented shoot/notice/rights and retention flow, access-controlled originals, takedown + propagation to derivative assets, license audit and server-authorized preview/full-download checks. Consult applicable law; not a claim of legal compliance. |
| **PQ-30** | **P1 future-sport dependency** | NOT_VERIFIED | **Surfing-specific assumptions leak into future football or other sports** (one athlete, ride boundaries, equipment clues and score/eligibility heuristics). | Versioned sport-specific event ontology, identity policy, GT labels and acceptance suites; football kept behind its own validation gate, not accepted based on surfing test scores. |
| **PQ-31** | **P2 editorial** | NOT_VERIFIED | **Technically correct but unappealing clips:** framing, pacing, transition timing, repeated shots, missed high-impact maneuver and platform-format mismatch. | Human editorial rubric + controlled blinded comparison and actual decoded previews; measure substantive quality separately from validity and engagement, without assuming virality. |

Every new gap is a *verification obligation*, not an assertion that the corresponding production bug has been reproduced. Existing PQ-01..17 remain open until their own exit evidence is collected.

### 9.3 Truth model — four different units, never conflated

1. **Source video**: cryptographic \`source_sha256\`, frame rate numerator/denominator, frame count, camera/recording lineage and approved GT revision. File basenames cannot establish identity.
2. **Physical ride/action**: stable \`ride_uid\`, source, athlete ID and start/end frame; zero or more annotated maneuvers/segments; explicit inclusion/exclusion and split rationale. An include segment is not necessarily a new wave.
3. **Canonical athlete**: one independently validated identity group per filming session; a local tracker ID or person_A label is *not* a global identity. Require positive joins, negative constraints and adjudicated unknowns.
4. **Product reel**: one primary output per eligible canonical athlete by current owner requirement, containing each distinct eligible ride once (multiple waves are multiple source segments in **one assembled reel**), no wrong athlete and no excluded content. A separate internal edit part or retry upload is not automatically a separately saleable/public reel.

**Conservation checks (fail closed on missing lineage):** count all expected ride UIDs; for each valid \`ride_uid\` assert a documented result \`included_once | explicitly_withheld_with_reason | unobserved_missing\`; assert no duplicated inclusion; per real athlete count primary published/approved reels <=1, and count ==1 when all acceptance gates pass. At the *event* layer ensure a source ride selected once; at the *product* layer ensure two genuine waves remain **two distinct ride records within one reel**. Also detect near-duplicate source recordings of the same real-world wave using evidence, not a hard-coded basename or timestamp equality.

**Policy nuance:** The existing single-part setting allows a reel to exceed the conventional 90-second social-edit budget; define platform-specific final packaging (possibly one complete purchased master plus platform-specific teasers) without silently dropping waves or labeling a split teaser as a second personal saleable reel. Do not alter this owner policy without authorization.

### 9.4 Test matrix — required proof of coverage

| Slice | Positive case | Adversarial/negative case | Gate |
|---|---|---|---|
| Ride eligibility | All GT-approved real rides | 0095 not eligible surf, 0155 failed takeoff; ambiguous short ride | Non-surf false inclusion 0; full valid recall or justified hold |
| Athlete within source | Same target throughout allowed window | 0094 A3 vs A4 handoff, visible bystander, tracker reset, foam occlusion | No mixed attributed frames; uncertain actor blocks release |
| Identity across sources | 0097 and 0115 same GT athlete | 0143 vs 0152 different athletes; same wetsuit/lookalikes; same basename two source SHA | Correct positive join + negative separation, both independently verified |
| Wave / segment cardinality | Source 0070 two real rides in **one** A1 reel; multi-maneuver same ride | Duplicate event, replayed same wave, false split across reels, improper merger of neighboring distinct rides | Every ride appears exactly once in expected athlete's product reel |
| Start/end windows | 0115 opening, 0104, 0162, 0151 complete finish | 0108 excluded tail, 0094 wrong-actor tail, early/late transition | Per-ride frame accuracy, no excluded/wrong-actor frame |
| Final media | Rendered video maps to approved actor/source/wave | Cropped-out surfer, transition leakage, retimed frames, black or broken output | Verified decoded media and frame-to-source provenance, not manifest alone |
| Run lifecycle | Replay same frozen sidecars and clean retry | Cancel, duplicate dispatch, missing asset, stale cache, model re-analysis | Same decisions on frozen input; no unsafe/duplicate published artifact |
| Future generalization | Unseen surfing conditions | New day/drone height/light, water foam, low-res preview, future football | Explicit holdout result; sport-specific green gate |

**Evaluator contract:** source SHA and GT version required; compare sets/unions of \`[start_frame,end_frame)\` intervals; count coverage per physical ride without multiplying overlaps; enforce valid per-part action lineage (never skip malformed rows); compute false selected, wrong athlete, split, duplicate, omitted, excluded, full/per-ride temporal error, subject-centered sampled-frame ratio and independently checked publishable. Each metric reports \`value, numerator, denominator, eligibility, evidence_revision\`. Missing data is \`BLOCKED\`, not zero or PASS. Separate \`reported\`, \`source_code_verified\`, \`replayed\`, \`media_reviewed\`, \`real_device_verified\`.

### 9.5 Safe PR #391 disposition — not merge-as-is

1. **Separate change sets:** isolate the member-key compatibility bug from track-gap/tail threshold relaxation and from the new GT reporting workflow. Do not approve a safety relaxation on aggregate publish-count improvement.
2. **First improve tests:** demonstrate red old/green new on the clip-index to source transform; same-filename/different-SHA negative; two actors in one source; cross-source group missing member or contradictory verifier; unknown/malformed proof remains blocked.
3. **Fix GT checker and workflow:** explicit fail on absent diagnostics, invalid \`baseline.json\`, missing or malformed metrics, incorrect source SHA, duplicate windows, 50%-only coverage, one excluded frame, +0.6-second human-adjudicated boundary, and correct-but-withheld regression. PR CI tests must exercise bad fixtures and check expected *failure reason*. Production-run comparison must run against exact historical artifacts and correct same-cohort SHA, not just the checker on synthetic data.
4. **Threshold A/B** on frozen sidecars: 2.0 vs 2.5 seconds, short-tail exception and alternatives; negatives for same actor vs A3/A4 handoff at 1.9/2.09/2.3/2.5/3.6 seconds. No weakened identity guarantee.
5. **Only after independent review and green gates**, merge narrowly scoped PR(s). Record exact head SHA and post-merge branch/CI result. Do not start a paid re-analysis just to create a favorable metric.

### 9.6 Root-cause workflow for every new failure — Engineering-OS-first rule

**Required research record before implementation:** \`gap_id | failing first stage | source_sha | GT revision | run/commit | failing media interval | old vs new observation | Engineering-OS paths searched | reusable package/version/license | minimal candidate change | red test | adversarial control | replay result | human visual review | cost delta | PR SHA | rollback\`.

- **Start with [Engineering-OS Video Analytics](https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/architecture-guides/cv/video-analytics.md)** for stage boundaries and telemetry; [Tracking](https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/architecture-guides/cv/tracking.md) for ID switch/occlusion and HOTA/IDF1; [CV Template](https://github.com/yotamfried-ux/Engineering-OS/blob/main/templates/computer-vision/README.md) for datasets/holdouts; [Supervision](https://github.com/yotamfried-ux/Engineering-OS/blob/main/external-systems/supervision/README.md) for bounding-box/trace comparison; [OpenMontage](https://github.com/yotamfried-ux/Engineering-OS/blob/main/external-skills/openmontage/README.md) for review checkpoints and render evidence.
- **Testing and proof:** [Testing FAST-PATH](https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/FAST-PATH.md) for cheapest falsifiable test; [Project Qualification](https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/project-qualification.md) for capability x evidence layer and negative controls. Reuse existing project tests and \`final_duplicate_guard\` before introducing a new package.
- **Improved-Engineering-OS:** [repository](https://github.com/yotamfried-ux/Improved-Engineering-OS) provides evidence/attribution architecture ideas; its README currently calls Stage 0 incomplete. Use the evidence model as **reference only**, not a proven deployed dependency. Any borrowed code must be license- and API-version-reviewed and tested independently.
- **Optional upstream:** [Ultralytics trackers](https://docs.ultralytics.com/modes/track/) for a BoT-SORT configuration experiment; [Roboflow Supervision](https://supervision.roboflow.com/) for overlays already within the project's version constraints; [ByteTrack](https://github.com/ifzhang/ByteTrack) for low-confidence association; [SAM 2](https://github.com/facebookresearch/sam2) for *limited* mask comparison; [FFprobe](https://ffmpeg.org/ffprobe.html) to validate actual outputs. Compare latency, accuracy, licenses and version compatibility first. A tracker cannot determine surfing eligibility by itself. No new paid service, new R2 bucket or GT migration is required for the initial measurement phase.

### 9.7 Delivery milestones and independent sign-off

| Milestone | Work package | Acceptance and output | Allowed next step |
|---|---|---|---|
| **M0 Inventory / controls** | Lock exact main SHA, GT digest, 24 annotated vs 29 input items, canceled-run impacts, artifact availability and zero-cost replay scope | Signed inventory with provenance; unreviewed sources marked UNKNOWN | Build offline test harness |
| **M1 Truthful evaluator** | PQ-07/08/13/16/19/21/24; per-frame coverage, strict schema, positive/negative fixtures, sealed holdout | Negative controls fail for right reason, no false "complete" and no GT inference leakage | Diagnose real failures |
| **M2 Identity & cardinality** | PQ-02/03/04/10/17/18/20/23; stable member evidence, actor-safe tracker bridge, athlete canonicalization | 0143/0152 separate; 0097/0115 together; 0094 safe; 0070 multiple waves one reel; no fake-positive joins | Tune action timing |
| **M3 Ride selection and exact timing** | PQ-01/05/06/11; eligible vs excluded, real catch and outcome, source-end cases | No invalid ride or prohibited tail; no missing accepted wave; human-adjudicated per-frame boundary checks | Render |
| **M4 Render/media review** | PQ-12/22/26/31; EDL, zoom/crop continuity, media lineage, editorial quality | Independent inspected media + automated overlays; approve/withhold each reel; no false publication | Controlled pipeline |
| **M5 Operational production rehearsal** | PQ-09/14/25/27; replay, retry, cancelled-run cleanup, cache, idempotency, security, resource limits | Run/asset consistency, cost and duration measured, alert+rollback proven on exact release SHA | App integration |
| **M6 Google Play & commerce** | APP register and PQ-28/29/30 | Google Play policy determination, release build signed/AAB tested, physical-device QA, user deletion/data safety, payment/entitlement/refund tests, content rights policy | Only then public launch candidate |

**Definition of Done / go-no-go:** zero unresolved P0 on reviewed release cohort; no wrong-actor or excluded frames in verified publishable reels; eligible rides accounted for exactly once; no duplicate saleable reel per verified athlete; complete render-side visual evidence; all required CI gates on exact merged main SHA and deployed artifact; separate operational recovery/security/mobile/store/payment evidence. Unknown or unreviewed cases must remain **BLOCKED/REVIEW**, never silently PASS. Release confidence can be high but cannot guarantee perfect performance on all future unobserved filming conditions.

### 9.8 Play/Grow regulatory and product gate (official reference check, 16 Nov 2026)

The Android register owns implementation. For pipeline release, **the product must not offer a paid in-app digital video through an unapproved external checkout** merely because Grow is the chosen processor. Verify distribution market, eligible program/enrollment and checkout surface. Official documents: [Google Play Payments policy](https://support.google.com/googleplay/android-developer/answer/10281818), [Billing choice program](https://developer.android.com/google/play/billing/billingchoice), [Google target API requirements](https://support.google.com/googleplay/android-developer/answer/11926878) (new app/update target Android **16 / API 36** from Aug 31, 2026, subject to the official current policy), [User data / account deletion](https://support.google.com/googleplay/android-developer/answer/10144311), [Grow developer portal](https://developers.grow.business/) and [Grow payments API reference](https://developers.grow.business/reference/create-payment-process). Grow requests must originate server-side; do not treat a redirect or raw webhook body as payment authorization. Before purchase enablement, require compliant Play policy route, authoritative entitlement/refund reconciliation, and tested signed preview/full asset access.

**Cost/operational constraints:** existing storage and GT remain authoritative; initial work is repository inspection, contracts, historical replay and compressed proxy review. No new infrastructure, full paid inference, automated production publishing or manual GT edits are authorized by this document. Explicit owner approval is needed before spending or production-side effects.

### 9.9 Open evidence ledger for this follow-up

| Claim / evidence class | Current evidence | What is NOT yet proven |
|---|---|---|
| 24 sources / 13 athletes / 42 include segments / 24 inferred rides | Independently counted from PR #391 branch's \`gtv1_frozen.json\` schema and its 3-frame \`_rides\` rule | Original source video hashes/storage contents, physical wave identities or visual correctness |
| One-reel flag enabled by default | Main \`performance_reel_policy._patch_editor\` / \`single_part\` | One reel per **actual** athlete across misclustered source groups and delivery retries |
| GT regression contract has permissive holes | PR #391 \`scripts/gt_product_check.py\` constants/\`compare\`/overlap logic | Real media-level precision/recall, excluded outputs and newly rendered quality |
| Member evidence mismatch in main | \`pipeline/identity_evidence.member_key\`, PR #391 change | That changing to basename will solve every collision / model-verifier error |
| Play/Grow release restrictions | Official Google Play and Grow documentation; APP register | Google Play enrollment eligibility, exact Grow merchant sandbox credentials, Play-approved live purchase path |
| PR #391 branch checks green | GitHub PR workflow status summaries | Full real-video replay, strict negative tests, exact deployed version or visual readiness |

**Maintain this evidence ledger on every future review** with URLs to immutable SHA/run artifacts and an explicit observer. Don't replace evidence with an AI-generated progress report.


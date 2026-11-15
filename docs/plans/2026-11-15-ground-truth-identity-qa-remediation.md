# SportReel — Ground Truth, Identity, Timeline and QA Convergence Remediation

**Version:** 2026-11-15 / proposal for engineering execution  
**Status:** IMPLEMENTATION SPECIFICATION — NOT YET IMPLEMENTED OR QUALIFIED  
**Primary evidence:** [Run #43710581656 vs frozen GT-v1](../evidence/run-43710581656-vs-frozen-GT-v1-20261115.md)  
**Target:** repair the *engineering pipeline* before optimizing cinematic quality, retention or virality.

## 0. Non-negotiable product and safety constraints

The canonical [README](../../README.md) contract remains: one correct featured athlete per reel; every eligible complete/usable action is accounted for; no excluded, duplicated or wrong-person moment; full continuous surfing rides; final QA fail-closed; silent portrait 2160×3840 @ 30 fps; raw video intact; app user identity **not inferred from biometric face matching**.

Use existing Supabase sportreel project, existing ground_truth schema, existing R2 sportreel bucket and studio/previews/ for access-controlled compressed visual review. Never create a database/bucket/server just to run this audit. Do not use frozen GT labels as live inference inputs (that would invalidate evaluation); GT is consumed by a separate post-run evaluator with read-only authorization.

Any changes to production data, source objects, migrations, paid LLM workloads, release settings or deployed workflows need explicit authorization. Never delete/overwrite approved GT, original media or old QA task history. No weakening of QA to turn a partial run green.

## 1. Prioritized engineering gap register

| ID | Priority | Observed failure / missing proof | Likely technical class | Primary code/data surface | Required correction |
| --- | --- | --- | --- | --- | --- |
| G01 | **P0** | 0095 all-excluded but produced a publishable reel; 0155 all-excluded in 85s draft; 0108 excluded tail in a publishable reel | Activity eligibility and selection not aligned with independently approved action quality | pipeline/stages/analyzer.py, pipeline/stages/selector_candidates.py, pipeline/performance_reel_policy.py, pipeline/selector_candidate_runtime.py, pipeline/missed_moment_rescue.py | Calibrate positive evidence of a **complete meaningful surf ride**; treat false positives as errors; preserve full eligible action coverage; do not hardcode GT source names |
| G02 | **P0** | 0143+0152 merged but frozen GT says different athletes; 0097+0115 split although GT says same | Cross-source identity calibration, semantic/model agreement mistaken for independent proof | pipeline/stages/identity.py, pipeline/identity_decision_engine.py, pipeline/identity_failsafe.py, pipeline/real_identity_gate.py | Identity association with explicit MATCH/NO_MATCH/UNCERTAIN, independent cross-source evidence, versioned pairwise traces; human adjudicate 0152 before modifying rules |
| G03 | **P0** | 0094 first actor shot extends ~5.45s into another actor's GT interval; 0151/0115/0104 lose approved portions | Actor-bounded interval refinement and source-to-output mapping | pipeline/complete_action_window_policy.py, pipeline/window_refinement.py, pipeline/cut_window_guard.py, pipeline/qa_reedit_window_contract.py, pipeline/quality_preserving_framing.py | Constrain complete-action window by *bound athlete continuity*, natural event outcome, adjacent distinct person; retain setup and landing; no unsourced extensions |
| G04 | **P0** | 0094/0140/0115 primary-track continuity only 0.367/0.409/0.410; 3 ambiguous cuts and 4 withheld drafts | Detector/tracker fragmentation, occlusion and incorrect track binding | pipeline/perception/, pipeline/primary_actor_policy.py, pipeline/real_identity_gate.py, pipeline/quality_preserving_framing.py | Track-level error taxonomy, overlay review, conservative in-source tracklet linking if evidence-backed; avoid identity switches or unsafe crop |
| G05 | **P0** | 179 cumulative qa_blocked tasks with zero attempts; only operator Send to re-edit promotes to pending; GET exposes latest 20 | QA task orchestration is intentionally manual with unbounded history and no autonomous convergence proof | integrations/supabase_uploader.py, pipeline/qa_gate_policy.py, web-api/src/app/api/operator/reprocess/route.ts, public.reprocess_requests | Bounded **safe auto-repair** for repairable defects, explicit manual queue for ambiguity, pagination/status aggregation, dedup and lifecycle; preserve history |
| G06 | **P0** | 14 drafts, 10 publishable, business outcome partial, run quality fail; GitHub Actions reports success | Operational success confused with product quality acceptance | pipeline/publishable_reel_policy.py, pipeline/publishable_runtime_integrity.py, scripts/record_publishable_business_gate_status.py, scripts/generate_run_quality_report.py, CI | Independent machine-readable QUALITY_GATE=PASS/FAIL/BLOCKED and clear incomplete business outcome even when execution exit=0 |
| G07 | **P0** | 25/25 EDL shots lack event_id; evaluation DB tables empty despite diagnostics predictions/EDL available | Missing stable end-to-end provenance and unclosed evaluation feedback loop | pipeline/edl_export.py, pipeline/prediction_export.py, scripts/export_pipeline_predictions.py, annotation-studio/server/evaluate.mjs, ground_truth.pipeline_predictions/evaluation_runs/edl_records | Stable source-scoped event IDs and an isolated, deterministic post-run evaluator; persistence under evaluator role, never train/test leak |
| G08 | **P1** | 3,083 of 3,174 GT box keyframes are suggested; 3,173 marked verified_correct but no verified_by/verified_at on ANY | Annotation provenance and independence of visual quality labels not proven | annotation-studio/server/annotations.mjs, ground_truth.annotation_revisions, approval UI | Preserve legacy records, add future approval provenance, spot-check sample by second reviewer, freeze adjudicated datasets without inventing timestamps |
| G09 | **P1** | QA warnings recur: PREMATURE_CUT, PRIMARY_ACTOR_UNCLEAR, source RECORDING_ENDS_MID_ACTION, NO_VISIBLE_ACTION | Repairable defects, source limitations, uncertain inference and final QA verdict conflated | pipeline/qa_gate_policy.py, pipeline/context_qa_gate.py, pipeline/qa_state.py, pipeline/orchestrator.py | Structured reason code, source/frame evidence, owner, repair action, retry outcomes, suppression only after proven resolution; never silence real warnings |
| G10 | **P1** | No actual MP4 pixels in diagnostic ZIP; cannot verify model's board-color conflict at 0152 or crop smoothness | Visual-review evidence not packaged as a private secure derivative | Existing review/ storage and studio/previews/; EDL/sidecars | Generate bounded compressed PRIVATE visual evidence package for human audit, with overlays, timestamps and strict access; no public disclosure |
| G11 | **P2** | PR #386 retention metrics on main, editorial flags off; last new run still unqualified | Editorial improvements not validated for correctness or retention | pipeline/retention_metrics.py, pipeline/narrative_policy.py | Only after P0 complete: compare A/B versions using identical athletes and source windows, full coverage, and visual reviewer |
| G12 | **P1** | Historical QA tasks accumulate per dated draft name, no clear currently-active vs historical partition | Backlog semantics and stale task reconciliation | public.reprocess_requests, web-api operator UI | Archive views by run/artifact lineage, triage old tasks without deleting; highlight only actionable tasks linked to current assets |

G01–G07 block full production qualification. Their exact underlying root causes require targeted reproduction and must not be assumed solved by renaming a defect, changing scores, or adding another generic Gemini call.

## 2. Implementation sequence and technical contracts

### Phase A — Freeze reproducible, independent evaluation (P0, first)

**Goal:** make every pipeline change testable without repeated paid full renders.

1. Keep frozen dataset GT-v1 digest b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9 unchanged. Verify every source by sha256/size and use its per-revision FPS/frame counts and per-segment athlete IDs.
2. Create or extend a deterministic evaluator under scripts/ (e.g. scripts/evaluate_pipeline_against_gt.py) that consumes ONLY: authorized read-only GT-v1 export, predictions/v1, EDL, publishable manifest, candidate ledger, final QA results. Prefer reusing annotation-studio/server/evaluate.mjs where compatible; do not build a second inconsistent matcher.
3. Produce per-source and per-athlete **TP/FP/FN** for complete-action eligibility; source-time union coverage; event boundary start/end deviations; false split/merge graph; wrong-person duration; excluded-source/out-of-bounds duration; and QA release flags. Separate maneuver/wipeout segments of one wave from a distinct second wave. Enforce one-to-one event matching to avoid counting a duplicated action as recall.
4. Identity matching must use (source_sha256, GT athlete_id, GT approved revision, per-segment interval) and (source_sha256, pipeline source_person_id, local track lineage, event_id, output_id); tracker numeric IDs are source-local. Do not infer source-unique athlete ownership for multi-person source 0094.
5. Join on **stable source-scoped event ID**. Preserve mapping through all stages: candidate → selected event → source window → render shot → final QA → draft → customer reel. EDL shot event_id cannot remain null.
6. Generate versioned comparison JSON and readable Markdown with exact source window, identity pair, reason code, reproducible seed, SHA and URL. Verify the evaluator against hand-checked fixture cases 0095, 0155, 0108, 0094, 0143/0152, 0097/0115, 0151, 0115.
7. Export only a **blind manifest** to the production pipeline. GT decision labels, identities, annotations, QA adjudications and test-split assignments remain inaccessible to the inference service.
8. Post-run evaluation, with a limited evaluator role, optionally persist predictions/EDL/evaluation in existing ground_truth tables. Report evaluation failure independently of the production workflow, not as a reason to delete media or corrupt old results.

**Phase A PASS:** a versioned, independently reproducible diff of the **same** run against GT-v1 exists; exact known mismatches reproduced; 25/25 source-scoped shot references resolvable or declared historical UNKNOWN; evaluation outputs cannot leak into inference; deterministic second replay gives same digest.

### Phase B — Stop all-excluded and wrong-identity output (P0)

**Eligibility / model:**
- Replace "score=high therefore a valid ride" with explicit, temporal positive evidence of a meaningful completed surfing action; distinguish takeoff vs sustained ride vs aborted takeoff; independently verify whether a fall/landing belongs to the completed ride.
- No hardcoded filename exclusion or direct GT lookup in inference: use 0095/0155 and 0108 as blind **regression tests** only.
- Diagnose whether false positives enter via analyzer, missed-moment rescue, score threshold, selector candidate runtime, or late render/publishable gate. Log the exact first stage that diverges.
- Preserve all other validated complete waves; never reduce recall just to make precision appear better.

**Identity:**
- Build a cross-source pairwise audit of source-person nodes; separate hard conflicts from semantic uncertainty and positive evidence.
- Evaluate 0143/0152 with actual private source proxy and independent manual adjudication; don't mutate immutable GT-v1 or force hard-coded board color rules.
- Reconcile 0097+0115 as one approved GT athlete but ensure only evidence-backed merges are allowed in live inference. Resolve false split without creating a false merge elsewhere.
- Handle repeated people, tandem and crossing subjects. Unknown must be review-required, not publishable based on two LLM descriptions that repeat the same hallucination.
- Report per-run identity purity / fragmentation, and retain formerly-correct negative control groups (0070+0108, 0112+0104+0126+0131+0140, 0160+0163).

**Phase B PASS on adjudicated GT:** ZERO falsely publishable excluded action, ZERO unadjudicated wrong cross-source merge or split, ZERO duplicate published athlete reel, with 100% eligible-athlete action-level accounting (correct reel or explicit justified rejection). No regression on correct existing clusters.

### Phase C — Repair actor-bound windows and track continuity (P0)

- Build frame-accurate source-to-output mappings with source FPS (59.94 can differ from output FPS 30), orientation, time bases, EDL blends and speed. Test at 0° and rotated footage.
- **0094 must not show athlete 9524 after the second athlete d805 begins unless the original footage independently establishes the first athlete is still the featured actor.** The GT 16.85s actor handoff is a high-value boundary probe, not a magic runtime constant.
- For 0115, 0151, 0104, 0094 compare setup, ride, maneuver, wipeout and natural close; do not truncate a complete wave or fabricate continuation after camera end.
- Add per-shot track presence %, max missing span, track switching, subject bbox inclusion and competing-person visibility. Use GT keyframes only after provenance review; optionally adapt the maintained [TrackEval reference](https://github.com/JonathonLuiten/TrackEval) for HOTA/IDF1 on independently vetted frames. Do **not** call the aggregate short-track rate a primary-actor IDF1 metric.
- Compare current BoT-SORT baseline with camera-motion compensation, track buffer and cautious in-source tracklet association before adding an appearance/ReID model. Verify actual supported Ultralytics API/version and CPU cost. No app-user face matching.
- On uncertain identity / occlusion, use a wider safe frame, visual review or an explicit reject rather than showing the wrong actor.
- Add regression for source handoff, multiple active surfers, tandem, underwater/whitewater occlusion, crop tracking jitter and athlete exit.

**Phase C PASS:** zero GT-supported cross-athlete contamination, validated full-action boundaries at agreed frame tolerance, no wrong-person crop or silent loss of action, and no regression in reviewed actor continuity. Publishability remains fail-closed when evidence is insufficient.

### Phase D — Close the QA repair lifecycle rather than only storing tasks (P0)

Current behavior: integrations/supabase_uploader.py intentionally creates qa_blocked tasks for operator approval, and web-api/src/app/api/operator/reprocess/route.ts promotes to pending only when the operator acts. That is task **persistence**, not automated repair. At inspection 179 historical qa_blocked tasks had zero attempts.

Implement a **bounded repair/review controller**, using existing components and explicit authorization:
- Stable task identity: run_id + source SHA/event_id + athlete_key + defect_type + output revision. Avoid duplicate tasks from renamed/re-rendered daily draft files.
- Lifecycle states or compatible mapping: detected → classified → repair_ready → repairing → rechecked → resolved OR manual_review / source_limited / hard_rejected / failed_max_attempts. Preserve every transition and evidence URL.
- **Automatically repair only provably safe defects**: extend a clipped ride within verified bound-tracker context, remove objectively measured dead time, correct deterministic crop or transition after source/actor validation. Do not "repair" mixed identity by arbitrary clip deletion or identity reassignment.
- Keep **PRIMARY_ACTOR_UNCLEAR, IDENTITY_SWITCH, GT disagreement and unresolved source limitations** manually reviewable. A SOURCE_LIMITED recording end is not an infinite automatic retry; expose why it cannot be fixed from the footage.
- Cap retries (existing max_attempts=3), log whether repair changed the source window/output and independent QA result, prevent identical no-op rerenders and cost loops, and escalate after no convergence.
- A QA PASS score must not overrule a separate actor/contract block. Consolidate final publishability into a single machine-readable reasoned decision with severity, reproducible evidence, and next_action.
- Add pagination/filtering and total outstanding count to GET /api/operator/reprocess. Show current-run, historical, auto-repairable and human-review-required separately. Reconcile old 179 tasks safely, **do not delete or mark resolved without actual proof**.
- Enhance scripts/verify_qa_reedit_tasks.py to verify lifecycle/convergence and not just task existence; provide a daily/status report from the same durable records, without assuming the user will manually click every task.

**Phase D PASS:** all fresh repairable QA issues are automatically triaged and either fixed with re-QA evidence or escalated with an actionable, nonduplicated reason. Zero indefinitely retrying/no-op repair loops. Historical queue fully visible and triaged without unsafe deletion.

### Phase E — Production gating, provenance, deployment evidence

- Keep GitHub Actions execution status distinct from **business readiness**: operational SUCCESS + quality FAIL / partial is NOT a complete successful product run.
- Publish run-scoped CI check/report: eligible GT athletes, valid outputs, QA-blocked, excluded segment contamination, identity merge/split, event recall, source-window overlap, manual-blocked. A full-production qualification requires all P0 gates PASS; an intentionally partial run can be classified PARTIAL but never presented as ready.
- Keep QA policy reason codes, repeated-defect counts and retry outcomes in a dashboard. Do not suppress recurring notes by string matching; resolve the underlying issue or record a persistent SOURCE_LIMITED decision with evidence.
- For future approved manual boxes, record actual verifier/verification timestamp and whether approval was a bulk semantic action or independent point-by-point review. Historical 3,174 boxes lack verifier/timestamp; preserve exact prior data and mark historical provenance level without inventing facts. Double-review 0143/0152 and failure cases.
- Make a **private, compressed 720p reviewer package** with frames near each disputed event boundary, per-frame actor/track bbox overlays, output-vs-source side-by-side and immutable source references. Use existing R2 prefixes and access controls; do not expose raw 4K or make review media public.
- Re-run baseline synthetic+offline regression FIRST. Run a controlled full pipeline only after budgets, current source SHA, backup and explicit live-run authorization are satisfied; compare against frozen GT-v1 using the independent evaluator. Re-evaluate run #43725044948 once its own diagnostics become available.
- Preserve source footage, protected GT, source-verified 4K / silent output and strict final QA.

## 3. Required test matrix and acceptance criteria

| Layer | Required evidence | Release acceptance |
| --- | --- | --- |
| Frozen dataset | 24 exact SHAs, immutable 24 revisions, frozen digest and split | No GT/inference leakage, no unreviewed data edits |
| Eligibility | 0095, 0155, 0108, plus synthetic complete/failed-takeoff controls | Zero approved excluded-source publication in adjudicated fixtures |
| Cross-source identity | 0143↔0152 false-merge, 0097↔0115 false-split, passing multi-source groups | Zero unresolved wrong merge/split in the approved 24-source benchmark |
| Same-source actors | 0094 actor A / actor B handoff; active overlapping surfers, tandem | Zero wrong-person seconds in approved benchmark, no identity switch |
| Action windows | Included 42 GT subsegments mapped to *physical rides*; 0094/0104/0115/0151 | All independently verified complete rides included/accounted for; report explicit interval IoU/start/end offsets |
| Tracking/frames | GT vetted keyframe boxes, trace continuity, overlays; optional TrackEval | Actor continuity and bbox quality improve vs measured baseline; no silent fallback to untracked inference |
| QA lifecycle | READY → repair → independent QA or MANUAL, 3-attempt cap; status API | No new orphaned tasks, duplicate loops or unresolved *repairable* QA work in completed qualification |
| Product run | Last completed 14 drafts / 10 publishable / 4 withheld baseline | No blocked critical QA in release-eligible outputs; partial outcome reported honestly |
| Output tech | FFprobe full 2160×3840 30 fps no audio; readable actor, proper source lineage | 100% canonical publishable outputs match product contract |
| Visual review | Authorized MP4/proxy, first/last frames and disputed times annotated | Human-reviewed conflicting GT case; no publishable ambiguous actor |
| Costs | Read-only evaluator plus minimal repro set before full run | No uncontrolled cloud spend or recurring new service |

Do **not** set arbitrary new accuracy thresholds from 24 videos. Pre-register thresholds for temporal IoU, bbox IoU and ID metrics on independently adjudicated frames, report confidence intervals and per-source failures, and keep catastrophic zero-tolerance rules for wrong-person / excluded-source publication. Use a holdout disjoint from any tuning set if a model or thresholds are tuned.

## 4. Project workstreams and suggested PR boundaries

1. **PR-A: Ground-truth evaluator and provenance** — deterministic source+event identity linker, EDL event IDs, GT-v1 read-only export, per-run mismatch JSON/MD, tests. No production inference behavior change.
2. **PR-B: Eligibility and source-event boundary fix** — specifically regress 0095, 0155, 0108; preserve good 0070/0108 action portions.
3. **PR-C: Correct athlete clustering** — independent pair verification, 0143/0152 adjudication, 0097/0115 same-athlete control, 0094 dual-actor tracking.
4. **PR-D: Time-window/track contract** — correct 0094 actor handoff and 0115/0151 missed parts; compare real proxy overlays.
5. **PR-E: QA convergence and operator backlog** — lifecycle, bounded repairs, pagination, old task status partitioning, one consolidated publication verdict.
6. **PR-F: Qualification and operations** — independent business gate, official evidence ledger, CI summary, budget controls, final real-video cross-run regression.
7. **After P0 only: editorial experiments** from PR #386 under off-by-default flags, requiring source-faithful visual A/B and no regression.

Each PR needs before/after fixture, focused test, regression suite, CI green, exact SHA, migration review where applicable, and unambiguous proof. Merge only after testing and code review; no merges or production modifications were performed in this documentation-only investigation.

## 5. Tools and documentation to use; prioritize the existing stack

| Capability | Source / existing component | Adoption guidance |
| --- | --- | --- |
| Pipeline GT evaluation | annotation-studio/server/evaluate.mjs, pipeline/prediction_export.py, scripts/export_pipeline_predictions.py | Extend and reuse; preserve blind split and independent evaluator role |
| Bounding-box and temporal detection evaluation | [FiftyOne detection/temporal evaluation docs](https://docs.voxel51.com/user_guide/evaluation/detections.html) | Optional local visualization/evaluation only; no new hosted service |
| Multi-object tracking benchmarks | [TrackEval HOTA/IDF1](https://github.com/JonathonLuiten/TrackEval) | Use only on independently vetted GT boxes, pinned compatible release/license |
| Tracker configuration | [Official Ultralytics tracking guide](https://docs.ultralytics.com/modes/track) | Benchmark BoT-SORT and safer track configuration; no unjustified new models |
| Annotation QA inspiration | [CVAT quality-control documentation](https://docs.cvat.ai/docs/qa-analytics/quality-control/) | Reference for validation/adjudication, do not migrate the established Studio |
| Frame/codec verification | [FFmpeg/ffprobe](https://ffmpeg.org/ffprobe.html) | Already in repo; make automated checks of source/output mapping and media specs |
| Storage/auth | Existing Supabase + R2 with scoped policies | Keep existing infrastructure, private proxy paths and read-only GT role |

## 6. Final required deliverables

- Frozen-source comparison report for both the baseline run and the next fully completed run (never blend outputs from two commits).
- Machine-readable per-source/per-event mismatch ledger including identity, window, QA, publishability and failure origin.
- Visual adjudication record for 0143/0152 and all three ambiguous actor windows; reviewer evidence protected.
- Executable regression suite with passing controls and failing-before/fixed-after cases.
- QA task lifecycle report: new, resolved, manual, source_limited, retry exhausted and stale/historical separately.
- Track accuracy and temporal recall metrics with independently vetted GT; uncertainty and exclusions documented.
- Final production qualification with exact CI URLs, commits, costs, protected data integrity checks and PASS/FAIL/BLOCKED gate verdict.

**Stop condition:** no claim of full production readiness until every critical eligibility, athlete identity, full-action coverage, safe media and QA gate is evidenced on a new completed run and approved visual holdout. Green GitHub Actions status alone is insufficient.

## 7. Execution constraints and current blockers

- Read-only audit complete: no code fixes, real video streaming, migrations, GT edits, task deletions, extra billing or reruns were performed by this document.
- **Needed for final visual proof:** authorized compressed review MP4s or scoped short-lived private URLs from the existing R2 bucket. The diagnostics ZIP has JSON/EDL/sidecars, not frames.
- **New run in progress at inspection:** #43725044948 at main SHA 185b6fd. Await its actual terminal state and artifacts before claiming changes work.
- Potential *manual GT/model conflict* on 0152 must be resolved by independent reviewer rather than automatically overwriting frozen labels or blindly trusting either one.

# SportReel — Deep Root-Cause Verification (2026-11-15)

**Status:** independent code-path review + two actual GitHub Actions diagnostic ZIPs + deterministic offline assertions. **No MP4 frames directly reviewed.** This document corrects causal overstatements in earlier PR #387 material.

## Source-of-truth evidence

- Previous run: [43710581656](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43710581656), SHA 9a03610a73d09784ef02f3a9c1d5c4cf44f7f29e, diagnostic artifact 14162886161.
- Most recent completed full run: [43725044948](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43725044948), SHA 185b6fd525fc0fab715c49f38da4a1613ccad9fe, diagnostic artifact 14167525908.
- GT-v1: frozen dataset ae844a94-b425-4f0a-8e4f-56034ab83425, digest b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9. This dataset is for a separate evaluation process, never inference-time access.
- Both runs: 14 output reels, 25 EDL shots with exactly the same source/output windows and selected subject-track IDs; 10 publishable, four withheld, final run-quality status FAIL, product gate PARTIAL despite successful execution. Zero of the 25 EDL shots have a canonical event_id. The diagnostic candidate ledger does have 25/25 selected candidates with inferred lineage; these are **different facts**.
- New run log: 29 source-analysis cache hits, 24 perception-sidecar cache hits. **The cross-source identity Gemini visual model DID run afresh**, so the persistent wrong-seeming pairing is not merely a recycled identity-model result. #386's editorial flags are off by default; identical EDLs do not demonstrate an enabled editorial fix failed.

## Where the discrepancy first appears — and where trust is incorrectly promoted

| Case | Earliest directly verified mismatch | Propagation / verified code mechanism | What is not yet proved |
| --- | --- | --- | --- |
| 0095: GT excludes 0–6.32s | Analyzer-selected event already claims real wave_catch score 9, 0–5.8s | performance_reel_policy.keep_event_for_performance_reel accepts score>=6 OR surfing event without an independently proven positive meaningful-ride verdict; EDL contains full 0–6.323s; pipeline marks publishable | Whether pixels show no meaningful riding or manual annotation should be adjudicated |
| 0155: GT excludes failed takeoff | Analyzer-selected event already claims wave_catch score 7, 0–7s | Later full 0–7.941s window in five-source draft; source no-ride text detection does not reject it | The five-source draft was **QA withheld**, NOT published; visual class still unverified |
| 0108: GT excludes tail after 6.82s | Analyzer candidate already ends at 9.0s (score 9), before editing | Render extends to 9.226s. Camera-end extension accounts for only ~0.23s, not most of the excluded ~2.18s | Actual landing/framing needs frame review; fixing only recording-end extension will not fix this |
| 0094: two approved GT athletes | Analyzer first actor event 4–22s overlaps second GT actor event starting 16.85s | Selected track 37 spans 1.42–27.36s (raw tracks 37 and 44); another track 154 spans 13.76–36.62s; window_refinement logs track gaps but does not actor-fence the event; final first shot 2–22.5s | Time overlap does **not prove wrong-person pixels**: concurrent people may both be in view. Actor/track overlays at 13–23s needed |
| 0143+0152: distinct GT athlete IDs | **Already grouped together at identity_trace.layers.model**, before post-processing; repeated in compile layer | Fresh identity._try_visual_cluster receives contact sheets derived from a chosen track **plus** analyzer text; identity post-process can promote structured compatible descriptions to _visual_verified; real_identity_gate passes visually labelled groups. The first grouping does NOT originate in _merge_duplicate_clusters | Actual 0152 board/garment color and whether contact sheet shows correct actor; GT and model conflict requires independent human adjudication |
| 0097+0115: same GT athlete | Already separate singleton groups in first visual model layer | _merge_check_pairs later has similarity threshold, trait filter and maximum eight checks; no later positive merge occurred | Whether candidate pair was excluded by ranking/threshold or evaluated and rejected requires pairwise candidate trace and actual crops |
| 0151: prematurely cut | Analyzer requests 0.5–7.4s; bound actor track 10002 ends at 5.138s | window_refinement has pad_end=1s; output EDL is 0.501–6.134s. This matches 5.138+1 to frame precision; source sidecar detections extend to 7.591s | **Exact cut mechanism proved.** Whether lost 10002 reappears as track 10003 (lasting to 6.71s) or was wrong actor requires human video comparison |
| 0115: missing approved opening | Analyzer marks source event beginning at 6.5s; GT included from ~0.07s; final output starts 4.5s | Bounded setup lead-in can recover only part of the early content; root is partly analyzer starting action too late, not merely editor cropping | Need visual action onset and source context confirmation |

## Deeper engineering mechanisms identified

### M1: Source model's semantic assertion becomes a trusted action

- pipeline/stages/analyzer.py::_parse_session creates event objects by parsing model JSON, filters by event duration, scores, and nearby starts. It does **not retain a canonical stable event_id**.
- pipeline/performance_reel_policy.py::keep_event_for_performance_reel is a negative-filter with a broad score/surf allowance. Absence of explicit failure text is not positive proof of a completed, usable ride.
- Diagnosis: the initial classification may be wrong before any downstream QA or render; merely changing the final selector or source-end tail cannot correct the source-level semantic decision.
- Required: typed ELIGIBLE/INELIGIBLE/UNCERTAIN, separate temporal evidence and source-action proof; preserve a candidate ledger of all rejected and accepted events and their original model text.

### M2: Identity evidence is correlated, not independently established

- pipeline/perception/runtime.py::_best_primary selects a track using persistence, spatial crop proximity, movement and confidence; it does not identify a human unambiguously. Event crop hint can be produced by the same source model.
- pipeline/runtime_quality.py::_track_samples and _identity_sheet generate contact sheets from the selected track. Wrong track binding can generate persuasive images of the wrong person.
- pipeline/stages/identity.py::_try_visual_cluster sends contact sheets AND text descriptions to Gemini; clustering is a model judgement. _merge_duplicate_clusters can merge descriptions without a new positive proof, and _merge_compatible_structured_clusters can set _visual_verified based on descriptor-score agreement. The _cluster_structured_verified shortcut can skip a genuine second visual verifier.
- pipeline/real_identity_gate.py::enforce_identity_gate contains kept_together_unconfirmed when enforcing one-reel-per-athlete; the result can remain grouped rather than release-blocked solely on this property.
- Diagnosis: no trustworthy separation between candidate similarity, source-track correctness and independently proven shared actor identity.
- Required: source-scoped track identity proof, explicit visual-evidence provenance, pairwise verification graph with MATCH/NO_MATCH/UNCERTAIN and a separate final publish gate. _visual_verified must never be set merely by structural descriptor compatibility.

### M3: Temporal model outputs are not actor-safe by construction

- pipeline/window_refinement.py::refine_event_window measures max track gap but explicitly does not act on internal gaps. A different actor, track switch or tracking interruption can thus occur inside a selected interval.
- pipeline/complete_action_window_policy.py extends based on analyzer-reported outcome, heuristic fall tail and recording-end tail; these additions must be revalidated against the target actor and immutable source frames.
- pipeline/perception/track_stitching.py merges tracklets using temporal proximity, bounding-box IoU and center distance within max_gap_sec=3.0, not independent appearance identity. Its 0094 source sidecar reports 46 raw -> 28 canonical tracks, 0143 reports 81 -> 22. That is a **potential** upstream identity hazard, not proof that a particular stitch was wrong.
- Diagnosis: no single actor-bound interval contract survives every wrapper and post-processing stage.
- Required: immutable source-frame ActionInterval, tracklet continuation with independent evidence, actor-handoff barriers, event ancestry and recorded reason for every window revision.

### M4: Observability can be green without a proven release decision

- pipeline/edl_export.py::record_clip copies optional event.get('event_id') or event.get('id'), but parser never guarantees either; hence all 25 EDL render shots lack an ID. The diagnostic candidate ledger infers selected lineage, but this is not the same as a canonical immutable event reference.
- pipeline/bootstrap.py stacks many monkey-patched wrappers whose order determines runtime behavior; validation of any individual helper without actual-bootstrap execution is inadequate.
- The pipeline does not automatically persist an independent frozen-GT evaluation as part of completed qualification (prior read-only Supabase inspection found zero rows in pipeline_predictions, edl_records, evaluation_runs).
- scripts/record_publishable_business_gate_status.py records partial product outcome and returns 0 while preserving run execution success. This is a valid *execution status* distinction but not a valid proof all customer reels are correct.
- Required: source-scoped event_uid at event creation, traced stage snapshots, deterministic post-run evaluator with strict role separation, output qualification proof and a distinct business-ready signal.

### M5: QA lifecycle is not a verified repair loop

- integrations/supabase_uploader.py::upsert_qa_reedit_task creates qa_blocked rows that require operator activation, an intentional manual policy. Prior read-only DB query found 179 historical qa_gate/qa_blocked rows with attempt_count=0. These are **not 179 new defects in one run**.
- pipeline/orchestrator.py handles pending operator requests, marks them queued, and later calls close_queued_reprocess. The latter updates **every** queued row to done without task-specific successful independent QA evidence. That global completion mechanism is a confirmed lifecycle correctness hazard.
- The QA task verifier proves task presence, not repaired output equivalence or no regression.
- Required: per-request idempotent lifecycle, scoped completion by exact repaired output hash, source+athlete identity, independent QA and policy proof; bounded retries, stable defect fingerprints and manual review for ambiguity. Historical tasks remain immutable.

## What cannot yet be verified as deepest physical cause

**UNKNOWN, needs review of actual source frames and original model input:**
- Whether 0151 track 10002 and 10003 are the same human, whether detector lost the box, or whether track stitching/target selection failed.
- Whether the 0152 model or GT labels misread board and clothing; what actual contact sheets show.
- Whether 0094 first surfer remains visible concurrently; temporal GT overlap alone is not wrong-person frame proof.
- Whether the 0095/0108 subjective surfing action was misjudged by the model or GT label needs adjudication.
- Whether source-video slicing or JPEG crop resolution harmed those exact decisions; code shows a possible mechanism but artifacts alone cannot isolate a causal intervention.

**Tests needed to move UNKNOWN to CONFIRMED:** capture authorized *private compressed* source/output proxies and identity contact sheets; overlay raw/canonical track IDs at disputed times; perform independent human visual adjudication blinded to model prediction; replay exact source through (A) cached semantic baseline, (B) safe cache-invalidated full native video model, (C) changed tracker/crop/threshold one variable at a time, within cost and production permissions; instrument the first stage where result diverges from reviewed GT.

## Required preventive architecture, in dependency order

1. **Instrument actual runtime and generate a failure-attribution DAG:** for source SHA capture activity slice, source-model raw response digest/cache key, candidate event UID, target track ranking, raw-to-canonical stitch chain, identity contact-sheet timestamps/boxes, every identity edge and verification evidence, every revised frame window, EDL mapping, QA verdict and release proof. Build an offline deterministic evaluator against frozen GT, never allow GT into inference.
2. **Fix upstream eligibility and actor binding before tweaking late QA:** positive action proof, no blind source-model score trust, source-local track continuation with explicit uncertainty, actor-bound action intervals, physical ride segmentation and full action coverage.
3. **Separate hypotheses from verification:** candidate matches may be scored by Gemini and similarity; a publishable identity match requires genuine provenance and independent confirmation sufficient for risk. Missing or conflicting evidence => review, not publish.
4. **Single final publication gate:** server-derived, versioned, fail-closed state with all mandatory identity, action, event UID, temporal, media and QA proofs; QA PASS does not override a contradicted actor/eligibility safety signal. Product success != GitHub Actions exit status.
5. **Verified QA resolution, not queue accumulation:** bounded safe repair when deterministic, per-task re-QA before terminal DONE, dedup/no-op detection, manual exception for uncertain vision, aggregate health metrics and separate historical backlog.
6. **Red/green regression:** 0095/0155, 0108, 0094 two actors, 0143↔0152, 0097↔0115, 0151 10002→10003 hypothesis, 0115 action onset; plus retained correct cross-source groups. Regression must exercise the actual bootstrap wrapper order, not only isolated unit functions.
7. **Acceptance:** zero known wrong-person/excluded-action auto-publications in *independently adjudicated* GT set, complete action accounting and explicit hard-rejects, bounded QA processing, protected media and signed output provenance, review on unproven claims, no silent drift on new datasets. The model cannot be guaranteed perfect on all unseen footage; safe no-publication on uncertainty is the enforceable invariant.

## What was actually verified in this investigation

**Fresh structured assertions PASS** for two-run unchanged 25-shot mapping, missing event_id vs existing diagnostic lineage, 0143/0152 first grouped in model layer, 0097/0115 first separate, 0095 and 0155 selected, 0151 5.138+1s cut with continuing source detections, and 10/14 publishable.

**NOT DONE:** raw video review, paid full pipeline replay, deployment modification, code bug fixes, migrations, automatic task closure, production release. The current evidence is enough to reject a late-only repair plan, not enough to blame a specific pixel detector or to guarantee perfect future outputs.

**Final disposition:** prior PR #387 identified genuine vulnerabilities, but several were propagators or missing guards rather than earliest first-failing stages. Implement the above stage-level proof system **before** attempting to solve all failures with additional prompts, threshold changes or QA suppression.

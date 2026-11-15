# SportReel — Root-cause diagnosis and preventive pipeline architecture

**Date:** 2026-11-15  
**Document type:** engineer-executable repair specification and no-regression contract  
**Status:** SPECIFICATION ONLY — code fixes, migrations, production reruns and visual adjudications NOT executed by this audit  
**Primary inputs:** [frozen GT-v1 comparison](../evidence/run-43710581656-vs-frozen-GT-v1-20261115.md), [existing remediation plan](2026-11-15-ground-truth-identity-qa-remediation.md), completed [Actions run #43710581656](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43710581656), last inspected main SHA 185b6fd525fc0fab715c49f38da4a1613ccad9fe.

## 0. Success criterion: guarantee safety, not infallible perception

There is no engineering basis for promising that all future unseen drone footage will always be identified correctly by AI. The enforceable guarantee is narrower and stronger:

1. **Nothing unsafe or unproven is automatically released.** No incorrect-athlete, excluded, mixed, duplicated, untraceable or critical-QA-blocked output is allowed to acquire a publishable entitlement.
2. Every submitted batch reaches a **terminal, accountable state** for each eligible detected athlete: \`PUBLISHED_VERIFIED\` OR \`REVIEW_REQUIRED\` OR \`SOURCE_LIMITED\` OR \`HARD_REJECTED\`; no silent disappearances.
3. Every confirmed bug becomes a deterministic regression fixture and policy invariant so that the *known class* cannot silently regress.
4. Novel/ambiguous cases are caught by evidence completeness/uncertainty gates and escalated safely, **not guaranteed to be auto-fixed or auto-published**.
5. Preserve existing immutable GT-v1 (24 SHA-identified sources, 45 approved segments, 42 include / 3 exclude), protected raw media, existing R2/Supabase, silent 2160×3840 30fps output, full viable surf action coverage, no face-based app-user recognition.

Do NOT cheat by reducing the denominator of eligible athletes, silently dropping hard cases, weakening QA, or learning test labels in the production inference path.

## 1. Proven mechanisms in code, uncertain causal attribution and precise remedies

Use \`CONFIRMED_CODE_MECHANISM\` versus \`RUN_ASSOCIATION_NEEDS_REPLAY\`; do not misstate that every code mechanism has already been proven the **sole** cause of an individual run failure.

### RC-01 — Descriptive text is allowed to create real cross-video identity merges (P0)

**Mechanism confirmed:** \`pipeline/stages/identity.py::_merge_duplicate_clusters\` merges clusters when their normalized text descriptions are equal and source videos do not overlap, without demanding positive independent visual confirmation. \`_merge_compatible_structured_clusters\` uses \`IdentityDecisionEngine.evaluate_pair\` scores and, on merge, sets \`_visual_verified=True\` despite using structured descriptors; \`_verify_multi_clusters\` can skip explicit visual verification when \`_cluster_structured_verified\` returns true. The final \`_post_process_clusters_inner\` also produces \`identity_decision_engine\` records for **trace**, not as a hard enforcement decision over every pair.

**Observed association:** GT says 0143 and 0152 are distinct athletes, while one publishable pipeline reel merges both. The independently reviewed images of 0152 have NOT been made available here; catalog-vs-model conflict requires visual adjudication rather than automatic label changes.

**Root fix:**
- Introduce typed \`IdentityEvidence\`: source_sha256, local_person_id, track lineage, apparel/equipment attributes, independently sourced visual comparison, model/provider/version, reason, evidence quality and uncertainty; keep apparel descriptions as **candidate retrieval**, never acceptance evidence.
- Replace unconditional text/score merge with a **pairwise graph** whose edges are \`MATCH|NO_MATCH|UNCERTAIN\`. A cluster may be merged only if every cross-source pair has a supported positive MATCH and no conflict, and its required visual gate has a real provenance record. Do not use transitive similarity alone to combine incompatible A/B/C nodes.
- Reserve \`_visual_verified\` exclusively for an actual image/video verifier with evidence reference and quality; replace ungrounded assignment with \`_structured_candidate=true\`, which cannot unlock publishing. No legacy metadata is silently reinterpreted as visual proof.
- On missing thumbnails, failed verification, or same-source identity overlap, use UNKNOWN→manual review. Track IDs are source-local; equal numeric track ID across different video files proves nothing.
- Audit the downstream \`real_identity_gate.enforce_identity_gate\`: the \`kept_together_unconfirmed\` branch under \`one_reel_per_athlete\` **must never be sufficient to publish**. Allow bundling for internal review but keep release eligibility false.
- Preserve pass controls for verified same-person groups; prevent a fix that merely forces every source into its own reel.
- **Tests:** 0143/0152 separate after adjudication; 0097/0115 same-athlete (when supported); A≈B, B≈C, A conflicts C (no invalid transitive merge); text identical but image conflict; visual verifier timeout; missing thumbnail; same-source multiple people; order-independent grouping. Exact graph/evidence verdict must be deterministic.

**Release invariant:** \`publishable => all cross-source grouping edges verified, same-source actor identity consistent, no UNCERTAIN identity\`.

### RC-02 — The cross-video gate can keep an unconfirmed cluster together (P0)

**Mechanism confirmed:** \`pipeline/real_identity_gate.py::enforce_identity_gate\` has a \`kept_together_unconfirmed\` branch when \`_one_reel_per_athlete()\` is true; it retains the union rather than splitting. \`_verified_single_track_per_source\` checks \`_visual_verified\` plus at-most-one tracker per source, but \`_visual_verified\` is not always an actual visual model call due to RC-01. \`_stable_track\` compares numeric IDs across clips, despite IDs being local (its guarded behavior needs targeted testing).

**Root fix:** separate structural grouping from *release evidence*. The grouped cluster can survive for visualization and operator triage, but must fail publication until verified. The final publishable manifest must record \`identity_verdict\`, all edge proofs and a stable group hash; no code path, including preview/delivery/payment, may bypass this gate.

**Release invariant:** no \`kept_together_unconfirmed\` group can have \`publishable=true\`.

### RC-03 — Surf eligibility is a permissive negative-filter rather than proven positive action (P0)

**Mechanism confirmed:** \`pipeline/performance_reel_policy.py::keep_event_for_performance_reel\` returns \`score>=6 or surf_event\` unless \`is_explicit_failed_takeoff\` detects specific hard rejection fields/phrases. This means a generic surfing classification can bypass the score and the lack of a known failure phrase can admit a nonviable ride.

**Observed:** 0095 (all GT excluded, no meaningful action) was published; 0155 (failed takeoff) was inserted into a withheld draft; excluded tail 0108 entered a publishable reel. The exact first stage of divergence (analyzer versus rescue versus selector versus window extension) is **not yet pinpointed**; inspect source-scoped decision trace and replay it.

**Root fix:** create typed \`SurfActionEligibility\` with \`VALID_COMPLETE_ACTION|INVALID_ACTION|UNCERTAIN\`, independent positive evidence: real takeoff/established riding, subject track spans the physical action, minimum observable activity quality, meaningful outcome when visible; explicit \`failed_takeoff\`, \`no_meaningful_action\`, \`not_riding\`, and contradiction reasons take precedence over optimistic scores. Rescue operates under the SAME typed policy and cannot mint a publishable event without revalidation. A valid short ride must not be wrongly dropped for arbitrary length. Do not hardcode filenames or access the GT database at inference time.

**Release invariant:** \`publishable => every included shot has a non-uncertain positive action proof and no excluded/ineligible evidence under live policy\`. Independently evaluate precision AND recall using frozen GT, not just false positives.

### RC-04 — Temporal window expansion is not strictly fenced by subject identity (P0)

**Mechanism confirmed:** \`pipeline/window_refinement.py::refine_event_window\` records \`max_track_gap_sec\` and gap start, but explicitly says the gap is *measured, not acted on*. It can keep a window spanning a subject-loss interval. \`pipeline/complete_action_window_policy.py\` then extends based on LLM \`outcome_end\`, fall heuristic and <=2 second camera-end tail; these paths guard some track-loss reasons but do not enforce a universal **actor/track segment interval intersection** or stop at an independently established handoff to another person.

**Observed:** 0094's first-athlete shot spans into a GT segment of another athlete; 0115, 0151 and 0104 have missing manually included action seconds. These are temporally grounded discrepancies; precise pixel-level root attribution and exact wrapper responsible still need a stage-by-stage replay.

**Root fix:**
- Define immutable \`ActionInterval\` in source frame coordinates: \`source_sha256, source_fps, person_local_id, track_lineage, first_actor_frame, last_actor_frame, action_start, action_outcome, confidence, occlusion_gaps, hard_actor_handoff_frames, permitted_context_pad\`.
- Maintain separate \`requested_window\`, \`validated_window\`, \`render_window\` and \`qa_reedit_window\`; every widening **must re-run** actor purity, source boundaries, visibility and full-action gates. Never treat a language-model \`outcome_end\` as independently verified geometry.
- For source 0094 the event cannot legally cross another athlete's confirmed segment without distinct evidence that the target remains the primary actor. Camera-end additions and lead-ins must be actor-safe; large track gaps lead to linked-tracklet verification or manual review, not implicit same-athlete continuity.
- Preserve all meaningful setup and ending (fall, kick-out, actual landing); a track disappearance at a legitimate splash can be natural outcome but needs measured evidence.
- Test fractional FPS, rotations, frame/second rounding, crossfades, multiple active surfers, recoverable occlusion, camera-stop mid-ride, setup/outcome extension and anti-crossing invariants.

**Release invariant:** \`every rendered source frame => is inside verified target action interval (or explicitly permitted bounded context with target visible)\`; else blocked.

### RC-05 — Tracking evidence is insufficient in known ambiguous windows (P0)

**Run evidence:** 0094, 0140, 0115 show primary-actor continuity around 0.367/0.409/0.410 in specified clips; QA gate correctly withheld those reels. Aggregate 101 short tracks of 278 is NOT equivalent to an athlete tracking failure rate.

**Likely causes requiring experiments:** drone camera motion, ocean whitewash occlusions, small subject boxes, per-source fragmented tracks, low detection confidence, and incorrect mapping of reopened tracklets. Do not invent the exact underlying model failure without overlays.

**Root fix:** controlled per-source tracker benchmark on separately vetted GT keyframes (and a visual review of the three failure windows); source-local tracklet graph with gap evidence, velocity, appearance and crop-box integrity. Evaluate existing BoT-SORT settings before adding costly models. Explicitly measure identity switches, gap duration, actor pixel visibility and missing context. More aggressive crop/zoom without actor proof is forbidden.

**Release invariant:** no unknown track switch in a publishable shot; insufficient confidence -> protected review.

### RC-06 — QA tasks are persisted but not driven to verified closure (P0)

**Mechanism confirmed:**
- \`integrations/supabase_uploader.py::upsert_qa_reedit_task\` intentionally sets \`status=qa_blocked\` and says it is not consumed until operator Send.
- \`fetch_pending_reprocess\` only picks \`pending\`.
- \`pipeline/orchestrator.py::_handle_reprocess_requests\` requeues source video(s) and marks the request \`queued\`.
- \`integrations/supabase_uploader.py::close_queued_reprocess\` runs \`UPDATE ... WHERE status='queued'\` **globally**, marking all queued tasks \`done\` without an explicit per-request final QA comparison. \`pipeline/orchestrator.py\` invokes that at phase end when operator note keys were applied. This is a genuine lifecycle correctness gap, independent of the 179 unattempted historical tasks.
- \`pipeline/qa_gate_policy.py::_persist_qa_reedit_task\` catches failures, logs a warning and skips persistence. \`scripts/verify_qa_reedit_tasks.py\` checks existence of active tasks, not verified closure.
- Operator GET \`/api/operator/reprocess\` limits to latest 20, so the complete historical backlog is not exposed through that endpoint.

**Read-only DB evidence:** 179 cumulative \`origin=qa_gate,status=qa_blocked\` rows all have \`attempt_count=0\`; only one historical qa_gate task \`done\`. Do not label 179 separate defects in this run or mark tasks resolved based on age.

**Root fix:** durable per-request, per-revision state machine (detected, classified, repair_ready, processing, awaiting_qa, resolved, source_limited, manual_review, retry_exhausted), with immutable transition log, idempotency key \`run_id+source_sha+local_person_id+event_id+defect_type+output_revision\` and fenced worker lease. \`done/resolved\` requires **that request's new output SHA, same target athlete and independently passing QA plus invariant re-check**. Remove or replace global \`close_queued_reprocess\` with scoped compare-and-swap update by request ID and evidence SHA.

Automatically perform bounded **deterministic, safe** repairs such as proven clipped endpoints or measurable crop/jitter correction after verifying actor constraints; an unclear identity, contradictory GT evidence, source-limited recording or uncertain perception must stay manually adjudicable. Max 3 attempts, fingerprint no-op output, stop repeated identical renders, report costs, no silent severity downgrade. Keep operator permissions and approval policy intact.

**Release invariant:** \`resolved => exists new product-verified output linked to same QA task\`; \`UNKNOWN => manual_review\`; no orphan or infinite retry; no task can be closed by unrelated run.

### RC-07 — Operational success is confused with all-product-output success (P0)

**Mechanism confirmed:** \`scripts/record_publishable_business_gate_status.py\` records partial publishing while explicitly leaving terminal execution status unchanged and returning exit code 0. In run #43710581656 GitHub shows success, quality report \`status=fail\`, publishable outcome \`partial\` (10 of 14). This separation is not inherently wrong, but the current communication allows a consumer to mistake a successful job for a fully correct batch.

**Root fix:** publish a mandatory immutable \`batch_qualification.json\` with independent dimensions:
- \`execution_state=SUCCESS|FAILED\`;
- \`product_state=PASS|PARTIAL|FAIL|BLOCKED\`;
- \`eligible_actor_count\`, \`published_verified_count\`, \`quarantined_count\`, \`hard_rejected_count\`, \`unaccounted_count\`;
- run/commit/GT benchmark version, source hashes, QA evidence URIs and all unresolved IDs.
Only **product_state=PASS** authorizes declaring full production batch success; PARTIAL is visible and may coexist with infrastructure success, but never treated as complete. Enforce the same verdict at operator UI, publishable manifest and delivery API. A QC failure must prevent delivery regardless of a runner exit code.

**Release invariant:** \`deliverable=true => product gate PASS for that output and all mandatory source-specific gates PASS\`.

### RC-08 — Missing permanent event lineage and no automatic independent GT feedback loop (P0)

**Mechanism confirmed:** \`pipeline/edl_export.py::record_clip\` writes \`event_id=event.get("event_id") or event.get("id")\`; 25/25 final EDL shots in analyzed run have null IDs. It logs and skips export failures rather than blocking rendering, appropriate for optional observability but insufficient for mandatory release certification. Prediction/EDL JSON exists as an Actions artifact; \`ground_truth.pipeline_predictions\`, \`edl_records\` and \`evaluation_runs\` had zero persisted rows at inspection.

**Root fix:** emit a stable, deterministic, *source-scoped* \`event_uid\` at first candidate creation. Keep a unique candidate ID plus immutable source/frame evidence through all transformations (rescue, dedup, identity, window extension, rendering, QA and delivery). Store parent IDs for merges and source-window revisions; forbid an output shot without bound source/event/track when intending publication.

Provide a **separate read-only post-run GT evaluator** (not inference) loading frozen GT revision IDs + source hashes and predictions/EDL and output manifest, comparing by source, actor and physical ride, not by description. Reuse existing Studio evaluator when possible, enforce versioned scoring and immutable run evidence. Never pass frozen approval labels to Gemini prompts.

**Release invariant:** every delivered frame/shot is traceable back to input SHA + typed eligibility + actor proof + event UID + QA verdict. Evaluation failure causes NOT_QUALIFIED, never guessed metrics.

### RC-09 — Layered runtime monkey-patches obscure the active policy precedence (P1 systemic)

**Mechanism confirmed:** \`pipeline/bootstrap.py\` installs many ordered wrappers that replace editor, analyzer and identity methods; comment explicitly says order matters. \`pipeline/complete_action_window_policy.py\` notes that a window-policy cut wrapper is not active after \`quality_preserving_framing.install()\` replaces it. Surf-specific editor helpers are not necessarily active on tracked entrypoints. This makes a code-reviewed single function insufficient to assert runtime correctness.

**Root fix:** replace overlapping monkey-patch chains **incrementally** with explicit typed stages/interfaces and a versioned policy registry: input/output contracts, provenance, installed order and stage digest recorded per run. Before refactor, add integration tests that import **the real tracked bootstrap** and assert the actual runtime call graph and invariants for all entrypoints. Any wrapper that can alter actor, window, event eligibility, QA or publishability must write a structured, compareable decision record and validate output. No silent fallback to unsafe legacy behavior.

**Release invariant:** all entrypoints share the same effective safety contracts, measured by execution (not static import inspection).

### RC-10 — Annotation acceptance and independent verification are conflated (P1)

**Observed in frozen GT-v1:** 3,174 box keyframes; 3,173 marked \`verified_correct\`; 3,083 origin=suggested; all 3,174 lack \`verified_at\` and \`verified_by\`. These counts **do not prove the boxes are wrong** but do not establish a fully independent human review, either.

**Root fix:** preserve immutable historical approvals; distinguish video-level approval, pointwise bbox verification, model-assisted suggested box, and blind second-reviewer adjudication. Capture real future actor/verifier/time, diff and source revision; never fabricate historic reviewers. Construct small independent holdout with verified challenging occlusions, 0143/0152 and actor transitions; benchmark trackers only on trustworthy labels.

**Release invariant:** no claim of verified per-frame tracker accuracy from unreviewed suggested boxes.

## 2. Reference architecture: narrow contracts instead of repeated prompt patching

\`\`\`text
Verified RAW source (immutable SHA)
  → detections + source-local tracklets + evidence
  → candidate actions (stable event_uid; all candidates retained in ledger)
  → SurfActionEligibility VALID / INVALID / UNCERTAIN
  → per-source actor-bounded ActionInterval
  → source-person graph (MATCH / NO_MATCH / UNCERTAIN)
  → verified athlete grouping (no unconfirmed union can publish)
  → complete-action selector, all usable rides accounted for
  → actor-safe render EDL (every shot has event_uid, subject and frame window)
  → layered QA: geometry + actor + event + technical + independent final reviewer
  → Publication Gate PASS / REVIEW / SOURCE_LIMITED / HARD_REJECT
     ├─ PASS → private preview + entitled full media
     ├─ deterministic REPAIRABLE → bounded safe repair → independent re-QA
     └─ UNCERTAIN / source-limited → human review, no publication
  → separate post-run frozen GT evaluator (READ-ONLY to inference)
  → immutable evidence ledger / dashboard / CI product-state
\`\`\`

### Mandatory output object, schema v1

\`\`\`json
{
  "schema": "sportreel.output_qualification.v1",
  "run_id": "...",
  "pipeline_sha": "...",
  "source_shas": ["..."],
  "athlete_group_uid": "...",
  "identity": {"verdict": "MATCH", "pairwise_proofs": [], "has_unconfirmed_edges": false},
  "events": [{"event_uid": "...", "source_sha256": "...", "source_frame_range": [0, 0], "actor_track_uid": "...", "eligibility": "VALID_COMPLETE_ACTION"}],
  "render": {"edl_digest": "...", "technical_contract_pass": true, "actor_purity_pass": true},
  "qa": {"final_verdict": "PASS", "critical_defects": [], "repair_task_ids": []},
  "product_state": "PASS",
  "publishable": true,
  "proof_digest": "..."
}
\`\`\`

Final \`publishable\` is **derived on the trusted server from the entire object**, not copied from a model response or mobile client. Invalid/missing fields fail closed. Do not hand out a paid full-media URL by checking only a generic boolean from an unverified row.

## 3. Detailed task sequence and PR plan

**PR-0 — Qualification harness, no runtime behavior change.**
- Freeze exact SHA inputs GT-v1 and run #43710581656, export baseline mismatch ledger and snapshot all 14 QA results.
- Add stable \`event_uid\` with deterministic legacy mapping, event ancestry, source-time frame mapping, and actual-bootstrap tests.
- Independently evaluate GT-matched events (physical waves vs wipeout/maneuver subsegments), wrong-person exposure and excluded-time overlap. Retain read-only separation; replay twice byte-identically.
- Add *red* regression tests for every concrete case and pass examples; preserve pre-fix failure evidence.

**PR-1 — Identity root repair.**
- Eliminate unconditional text-only merges and false \`_visual_verified\` provenance.
- Make \`MATCH/NO_MATCH/UNCERTAIN\` enforceable all the way through publication (not just logs).
- Correct \`kept_together_unconfirmed\` release behavior; preserve independently verified same-actor cross-source grouping.
- Visual adjudication of GT vs models for 0152 required before declaring all 24-source GT identity outcomes resolved.

**PR-2 — Eligibility and anti-contamination.**
- Positive surfing action evidence policy and single authoritative admission gate reused by analyzer, rescue, selector, renderer and publishable gate.
- Regression 0095, 0155, 0108; explicit check no eligible wave was lost (e.g. 0070/0108 good portion).

**PR-3 — Time windows, actor tracks and full action.**
- Fenced actor-bound interval, gap/handoff semantics, replayable window revisions, tracklet stitching where justified.
- Regression 0094 mixed actors and 0115/0151/0104 lost action segments.
- Inspect authorized private 720p review proxies and time-stamped overlays; compare original vs corrected (same source), verify the actual fall/exit and crop subject.

**PR-4 — Repair/review state machine.**
- Scoped QA attempt IDs and lease/idempotency, remove global mark-all-queued-done path.
- Safe repair classes + re-QA + cap/no-op detection + operator escalation; reprocess API pagination and summary.
- Historical 179 tasks: classify actionable vs stale/historical and link to original run without pretending to repair or silently changing status.
- Test concurrent workers, crash after state transition, cancelled runs, duplicate webhook/dispatch, partial batch, attempted repairs producing identical output, producer downtime.

**PR-5 — Business gate and independent release verification.**
- Signed immutable output-level proofs and batch-level execution/product verdict.
- Reconcile GitHub-success-but-product-partial behavior. Ensure delivery and approval honor exact proof digest/revision and reject stale passes.
- Export evaluator artifacts and run diagnostics to existing R2/CI/Supabase paths with role isolation; no new infrastructure required.

**PR-6 — Qualification against NEW full pipeline run (approval required for paid/full production execution).**
- Offline deterministic + synthetic+real GT subset first, no new cloud spend until needed.
- Recheck the currently running #43725044948 when complete and compare **against its SHA**, not silently mixing runs.
- Run a new constrained E2E batch with approved inputs; verify every source athlete and all relevant outputs, QA, store/cost and delivery. Keep unsafe/bad/missing-evidence outputs quarantined.

**PR-7 (later) — Marketing/edit quality.**
- Only after P0 safety: switch on controlled retention/shot-order flags from PR #386 if visual A/B and no safety regression validate them.

## 4. Mandatory test matrix (must be enforced, not merely documented)

| Test | Fixture / stimulus | Required outcome |
| --- | --- | --- |
| T01 negative eligible action | 0095 all excluded, 0155 failed takeoff | NOT publishable; explicit evidence code; no loss of other eligible riders |
| T02 excluded subwindow | 0108 after 6.82 seconds | No unapproved tail in publishable output |
| T03 same-source handoff | 0094 two different GT identities | No cross-athlete render frames; no automatic merge of same-source people |
| T04 cross-source false merge | 0143 and 0152 (subject to human adjudication) | Separate or review-required, never blindly merged based on matching descriptive text |
| T05 cross-source false split | 0097 and 0115 | Correct one-person grouping on validated positive evidence, no unrelated merges |
| T06 weak/fragmented track | 0094, 0140, 0115 plus whitewash/occlusion fixtures | Safe crop or REVIEW_REQUIRED, no wrong-person tracking |
| T07 action boundary | 0115, 0151, 0104, end-of-camera | Full real ride, verified natural outcome or SOURCE_LIMITED; no invented tail |
| T08 stable lineage | candidate → EDL → QA → reel | 100% released shots have event_uid, source SHA, actor and verified interval |
| T09 QA resolution | duplicate request, timeout, no-op rerender, wrong repaired athlete | No false DONE; retry cap and manual escalation |
| T10 gate bypass | QA PASS but primary actor failed; execution succeeded but product partial | Publishable false, manifest and UI agree |
| T11 wrapper precedence | tracked GitHub, manual and reset entrypoints | Identical safety policy and actual call-path proof |
| T12 GT integrity | frozen 24 sources, revision SHA, holdout | No mutation or inference read; deterministic evaluator outcome |
| T13 media contract | approved full outputs | Exactly 2160×3840 30fps portrait no audio and acceptable encoded quality |
| T14 historical QA migration | 179 older blocked tasks and new tasks | No unsafe deletion, clear backlog visibility, historical triage |
| T15 cost and failure | model timeout, DB outage, storage outage, worker crash | Fail closed, bounded attempts, no paid runaway loop |

A test is not sufficient until it is shown **red against baseline then green against fix**, with legitimate live-runtime integration exercising the code, not merely isolated mocks.

## 5. Formal acceptance gates and release policy

- **GATE-A Inference safety:** every published included event has positive eligibility + actor evidence; zero excluded-window contamination in independently adjudicated GT fixtures.
- **GATE-B Identity:** zero confirmed wrong merges/splits and no unverified cross-source group published; human adjudication required for 0152 if still conflicting.
- **GATE-C Completeness:** every independently confirmed usable physical wave is present exactly once for the correct athlete, or recorded justified exclusion; separate physical ride and maneuver/wipeout segment counts. No assertion of 100% recall without a held-out benchmark.
- **GATE-D Temporal and tracking:** no actor switch in certified output, verified start/end at pre-registered frame tolerance, uncertain/out-of-source tail blocked.
- **GATE-E QA convergence:** new tasks either resolved with linked independent QA or explicitly terminal manual/source-limited; no global close, no orphaned task, no unbounded retries. Old tasks accurately classified.
- **GATE-F Product release:** actor, event, EDL, QA, media specs and paid-access proofs independently agree. \`PASS\` required per output; a batch may report PARTIAL until all eligible athletes accounted for.
- **GATE-G Reproducibility:** exact source hashes, commit, model version, dataset and evaluator versions, 2 identical offline replays and a controlled full run. Tests/metrics attached to PRs.
- **GATE-H Operational integrity:** rollback, secure secrets, no leaked GT into inference, existing R2/Supabase only, no production modifications or unapproved spend.

Verdicts: \`PRODUCTION_READY\`, \`CONDITIONALLY_READY\`, \`NOT_READY\`. Never report PRODUCTION_READY based only on CI green, an LLM QA score, merged code or an artifact without pixel-level validation.

## 6. Immediate execution instruction for engineering agent

1. Read these exact files: \`pipeline/stages/identity.py\`, \`pipeline/identity_failsafe.py\`, \`pipeline/real_identity_gate.py\`, \`pipeline/identity_decision_engine.py\`, \`pipeline/performance_reel_policy.py\`, \`pipeline/window_refinement.py\`, \`pipeline/complete_action_window_policy.py\`, \`pipeline/edl_export.py\`, \`pipeline/qa_gate_policy.py\`, \`integrations/supabase_uploader.py\`, \`pipeline/orchestrator.py\`, \`pipeline/bootstrap.py\` and \`web-api/src/app/api/operator/reprocess/route.ts\`. Compare exact runtime behavior at the current main SHA.
2. Implement **PR-0 first**. Before changing heuristic thresholds, show red reproductions for each confirmed mismatch and typed decision lineage demonstrating where the first wrong decision arises.
3. Split independent fixes into the PRs above and prevent cross-PR monkey-patch conflicts with actual-bootstrap test. Do not auto-merge if required evidence missing.
4. Preserve full raw and GT data, no production writes or paid model/rerun calls without authorization. Read-only Supabase and GitHub artifacts suffice for initial evaluator development.
5. Report at each milestone: first-failing stage, exact source/event IDs, before/after metrics, unit+integration+real-video test evidence, costs, regression risks and remaining UNKNOWN.
6. Final status only after current code and fresh real outputs are verified — known failure classes are *guarded* even if unseen AI inputs still need review.

**This is a root-cause prevention plan, not a claim that the pipeline is already fixed.**

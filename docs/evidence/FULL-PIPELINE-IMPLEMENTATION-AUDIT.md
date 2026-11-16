# SportReel — full pipeline implementation audit (2026-11-16)

Spec: `docs/plans/2026-11-15-pipeline-root-causes-and-preventive-architecture.md` (PR #387, head `098bb19`).
Branch `ccr-3f12fc2f-pdvirt`, draft PR #390, base `main` = `e26418a` (PR #389 merged).
Commits on the branch: `19aa3d7` (athlete/output binding), `881cb57` (P0-A..P1-E, identity evidence v2), `e3443c9`
(output qualification), `eb0f973` + `530e7e8` (offline GT evaluation), `33fc133` (batch qualification, runtime
registry), `2a4a395` (repair lifecycle, backlog paging, GT evidence levels), and the commit adding this report.

**Evidence classes used below.** *Red*: the defect reproduced on the code before the fix (commit named). *Green*: a
contract test exercising production functions (or the real bootstrap) passes on the final commit. *Real runtime*:
evidence from a real pipeline run or real data. No pipeline run has executed the code of this branch, so no
requirement here is verified on real video; the column says what real evidence exists.

## 1. Root causes RC-01 … RC-10

| Req | Code location | Original failure | Fix | Red | Green | Real-runtime evidence | Final status |
|---|---|---|---|---|---|---|---|
| RC-01 text/score identity merges | `pipeline/identity_evidence.py`, `stages/identity.py` (verifier, pair check), `identity_failsafe.py` | `_visual_verified` from text; any caller could write `method=image_verifier` | Evidence v2: image SHA-256 per member, model, response digest, timestamp, MATCH edge per cross-source pair, tamper digest; `covers` rejects anything less | #388/#389 (bare flag passed); `881cb57`: `stamp(method)` without images passed | `test_release_safety_invariants_contract` I1–I6 + new I2 negatives; `test_verified_cluster_merge_contract` | Run 43816344303: 5 image-verifier calls, one image per member; 0143+0152 confirmed by the model (GT: 2 athletes) | Code done; **BLOCKED_VISUAL** (0143/0152, 0097/0115) |
| RC-02 unconfirmed group kept together | `real_identity_gate.py`, `output_qualification.identity_verdict` | `kept_together_unconfirmed` could publish | Gate pass carries the evidence digest; multi-source reel without a digest-backed pass, or with several actors of one source, is a qualification issue (withheld) | #388 | `test_output_qualification_contract` Q3, Q6 | none on fixed code | Code done; NOT_TESTED in runtime |
| RC-03 permissive eligibility | `output_qualification.classify_action`; `performance_reel_policy` (rescue filter) | admission = analyzer score / surf words; rescue admitted INELIGIBLE siblings | `VALID_COMPLETE_ACTION / INVALID_ACTION / UNCERTAIN`: VALID needs rating + tracker binding + CV activity of the target track + coherent window; explicit no-ride INVALID; CV contradiction or missing evidence UNCERTAIN; only VALID publishes; per-event rescue admission | baseline GT eval: 0095 348/379, 0155 420/476 excluded frames selected | Q1; `test_missed_moment_rescue_contract` | none on fixed code | Code done; **BLOCKED_EXTERNAL_APPROVAL** (run) + BLOCKED_VISUAL (0095/0155) |
| RC-04 window not fenced by actor | `output_qualification.action_interval`; `missed_moment_rescue._measure_actor_span` | `window_refinement` measured gaps without acting; tails could pass the actor | requested / validated actor span / rendered / QA windows; tail past the last verified actor frame (beyond pad, unless measured fall), lead before the actor, track gap > 2 s inside the shot, unvalidated span → withheld; recording-end tail marked SOURCE_LIMITED | baseline: 0094 selected 239–1319 crosses A2's ride (from 1010); 0108 tail 131/144 | Q2 | none on fixed code | Code done; BLOCKED_VISUAL |
| RC-05 weak tracking | same; rescue uses sidecar activity + measured span over proven continuation tracks | rescue asserted `primary_actor_clear`/`identity_continuity` | measured evidence only; asserted fields ignored | `881cb57` code read | Q2; rescue contract | none | Code done; box GT is UNVERIFIED_GT |
| RC-06 QA not driven to closure | `reprocess_binding.py`, `supabase_uploader.py` (claim/close/recover/upsert), `repair_lifecycle.py`, `orchestrator.py`, web-api reprocess route | global close; source-wide `done`; invalid binding → legacy `done`; zero-row closure reported; stale queued forever | binding modes; identity-safe match; exact part + byte hash + QA PASS; CAS everywhere; stale-queued recovery; state machine with allowed transitions; backlog paging + summary | `19aa3d7` reproductions (see `docs/evidence/FINAL-ROOT-CAUSE-QUALIFICATION.md` §12) | `test_reprocess_binding_contract` B1–B8, `test_repair_lifecycle_contract` | repair-evidence columns applied in production (approved); no reprocess run yet | Code done; NOT_TESTED in runtime |
| RC-07 execution vs product success | `scripts/write_batch_qualification.py`, diagnostics wrapper | green workflow read as complete batch | `batch_qualification.json` (execution_state / product_state, per-athlete state, unaccounted, proof digests), mirrored into `pipeline_runs.meta` | run 43816344303: execution SUCCESS, product (re-qualified offline) FAIL 0/14 | `test_batch_qualification_contract` | offline re-qualification of 43816344303 | Code done; first real artifact on next run |
| RC-08 lineage + GT evaluation | `event_identity.py`, `publishable_reel_policy._action_evidence`, `output_qualification` (lineage), `annotation-studio/scripts/evaluate-offline.mjs` | EDL ids only; no persisted evaluation | per-shot action evidence in manifest; lineage required to publish; offline read-only evaluator (studio's own) with physical-ride and contamination views | — | Q4; `annotation-studio/tests/evaluate_offline.test.mjs` (5), evaluator tests 9/9 | GT-v1 vs runs 43710581656 / 43816344303: 24/24 rides, 3/3 excluded segments contaminated, digests `77220cd1`/`3f7db457` | Done offline; production persistence of evaluations needs approval |
| RC-09 monkey-patch precedence | `pipeline/runtime_policy_registry.py`, `bootstrap.install_post_orchestrator_patches` | unit tests ≠ runtime call path | effective chain per stage + execution probes (identity gate, output qualification); fail-closed; artifact per run; all 4 entrypoints | — | `test_runtime_policy_registry_contract`, parity + logical-consistency tests | none (next run writes the artifact) | Code done |
| RC-10 annotation evidence | `scripts/gt_evidence_levels.py` | approval ≠ box verification | levels SUGGESTED / MARKED_VERIFIED / ATTRIBUTED_VERIFIED / ADJUDICATED | — | `test_gt_evidence_levels_contract` | GT-v1: 3,174 keyframes, 3,173 marked verified, 0 with reviewer/time → UNVERIFIED_GT | Classification done; independent holdout needs human labelling |

## 2. Test matrix T01 … T15

Run with `scripts/run_release_matrix.py` on the final commit; every row's contracts pass. *Real video on the
fixed code: no* for every row.

| Test | Fixture | Contracts (all pass) | Vulnerable baseline | Real video | Limitation |
|---|---|---|---|---|---|
| T01 invalid action | 0095, 0155 | output_qualification Q1, root_cause_fixes | 0095 348/379, 0155 420/476 excluded frames selected | baseline only | ratings 9/7: needs run + visual |
| T02 excluded subwindow | 0108 > 6.82 s | Q2 | 131/144 excluded frames selected | baseline only | tail with actor visible not detectable without vision |
| T03 handoff | 0094 | Q2/Q3, release_safety I4 | window 239–1319 crosses A2 (1010) | baseline only | handoff inside one track id caught via gap only |
| T04 false merge | 0143+0152 | release_safety I1–I6, verified_cluster_merge, merge_check | model confirmed merge | VISUAL_REVIEW_REQUIRED | confident wrong model verdict |
| T05 false split | 0097+0115 | release_safety I3, merge_check | missed merge | VISUAL_REVIEW_REQUIRED | merge recall |
| T06 weak track | 0094/0140/0115 | Q2, rescue | — | none | UNVERIFIED_GT boxes |
| T07 boundaries | 0115/0151/0104 | Q2, rescue | 0115 starts at 389 vs 4 (cov 0.55) | baseline only | frame tolerance unmeasured |
| T08 lineage | candidate→reel | release_safety E1–E3, Q4, binding | 25/25 EDL ids, 0 in manifest | partial | manifest ids since #389 |
| T09 QA resolution | dup/timeout/no-op/wrong athlete | binding B1–B8, lifecycle | false `done` reproduced on `19aa3d7` | none | no reprocess run |
| T10 gate bypass | PASS but actor failed; partial batch | Q5, batch_qualification, qa_gate_block, business_gate | GitHub success, product partial | offline re-qualification | proof digest not stored server-side |
| T11 wrapper precedence | 4 entrypoints | runtime registry, parity, logical consistency | — | none | registry artifact on next run |
| T12 GT integrity | GT-v1 | gt_evidence_levels, evaluate_offline (node) | — | offline evaluation | UNVERIFIED_GT boxes |
| T13 media | 2160×3840 30 fps silent | silent_output_policy, quality_first_4k | — | previous runs | visual quality |
| T14 backlog | 202 rows | lifecycle, binding (legacy mode) | 185 qa_blocked, 0 attempts | read-only counts | operator reconciliation |
| T15 failure/cost | crash, DB failure, timeout | binding B7 (recovery), cost_time | stale queued forever | none | storage outage via existing tests |

## 3. Acceptance gates A … H

| Gate | Status | Evidence | What is missing |
|---|---|---|---|
| A Inference safety | **BLOCKED_EXTERNAL_APPROVAL** (+ BLOCKED_VISUAL) | code withholds UNCERTAIN/INVALID shots and excluded-window tails (Q1/Q2); baseline contamination 3/3 | a controlled run on this code; visual review 0095/0155/0108 |
| B Identity | **BLOCKED_VISUAL** | image evidence bound to members, gate digest required (I1–I6, Q3/Q6) | adjudication 0143/0152, 0097/0115 |
| C Completeness | **BLOCKED_EXTERNAL_APPROVAL** | baseline 24/24 physical rides covered | the fail-closed rules may withhold valid rides: must be measured on a run |
| D Temporal/tracking | **BLOCKED_VISUAL** | interval rules (Q2); 0094 crossing shown in frames | run + overlays; box GT unverified |
| E QA convergence | **NOT_TESTED** (runtime) | contracts B1–B8, lifecycle; red reproduced | a reprocess cycle in a real run |
| F Product release | **NOT_TESTED** (runtime) | proof derived from evidence, approval API refuses technical issues, batch verdict | proof digest server-side (migration), real run |
| G Reproducibility | **BLOCKED_EXTERNAL_APPROVAL** | deterministic offline evaluation (stable digests), source SHAs in proofs | two replays + controlled run |
| H Operational integrity | **NOT_TESTED** | no production writes beyond the approved migration; no GT read by inference (grep: comment only); evaluator writes files only | rollback not exercised; cost of a run unmeasured |

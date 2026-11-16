# SportReel — final root-cause qualification (2026-11-16)

## 1. Branch and commit

Assessed: `main` at `2b7d4cf` (PR #388 merged) plus this branch `ccr-3f12fc2f-pdvirt` (PR linked in the commit).
Runs compared: 43710581656 (`9a03610`), 43725044948 (`185b6fd`, per #387 identical shots to the previous), and
43816344303 (`2b7d4cf`, first run after #388, artifact 14204326687). No video was watched; no production data
was written; no pipeline was re-run.

## 2. Root causes and status

| # | Root cause | Where | Status |
|---|---|---|---|
| M2a | `_visual_verified` set from text agreement | `identity.py` structured merge, verifier shortcut, `identity_failsafe` | Fixed in #388. Run 43816344303: every multi-source cluster got an image-verifier call with one image per member (5 calls; 516 image tokens for 2-member, 1,290 for 5-member clusters) |
| M2b | Same tracker number across sources passed `_stable_track` | `real_identity_gate.py` | Fixed in #388; widened tests here (I1, I3, I4) |
| M2c | A pair check (one image per cluster) confirmed a larger merged cluster | `identity._verify_merge_candidates` | Fixed in #388; a final whole-cluster verification runs last |
| **M2d** | **The release gate trusted an inherited boolean.** Any code that set `_visual_verified=True`, or a cluster that changed members after a check, passed `visual_verified_per_source_tracks`. Red on `main`: "I2: a bare _visual_verified flag passed the gate" | `real_identity_gate._verified_single_track_per_source` | **Fixed here.** `pipeline/identity_evidence.py`: a positive image check records the exact member set and its hash; the gate requires evidence covering exactly the current members. Evidence survives `_strip_internal_fields`; a structured merge or any member change invalidates it |
| M2e | Chain A~B, B~C with an A/C conflict | `_split_impossible_clusters` | Already correct (all pairs checked); now regression-tested for every order (I5) |
| **M4a** | **Event ids reached the EDL but not QA or the manifest.** Run 43816344303: 25/25 EDL shots carry `ev2_…` from the analyzer; 0/25 events in the decision trace, none in the manifest | `draft_identity_metadata._EVENT_KEYS` whitelist; manifest parts | **Fixed here.** The serializer keeps `event_uid`, origin, schema, source ref, analyzer window and `identity_gate`; every manifest part lists `event_uids` |
| **M4b** | **A reel could publish with an orphan shot or one event used twice** | `record_athlete_outcome` | **Fixed here.** `missing_event_provenance` / `duplicate_event_uid` are technical issues: not render-ready, not publishable |
| **M4c** | **Two late events with equal window, type and track shared an id** | `event_identity.ensure_event_uid` | **Fixed here.** Run-wide issued-id registry; a colliding non-analyzer event gets a counter. Rescued events get their id where they are created (`missed_moment_rescue`), not at clip time |
| **M5a** | **Two workers could process the same request** (fetch `pending`, both mark `queued`) | `_handle_reprocess_requests` | **Fixed here.** `claim_reprocess`: update matches only while the row is `pending`; the loser skips. The claiming run is written to the existing `last_pipeline_run_id` |
| **M5b** | **A request closed under any run, and a failed write aborted the rest** | `close_reprocess_requests` | **Fixed here.** Closure filters on `status='queued'` and the claiming run id; each write is isolated (`close_failed` is reported, the others proceed) |
| **M5c** | **`done` ignored the request's own defect** | `reprocess_outcomes` | **Fixed here.** `done` needs reels from its sources, all publishable, and none still carrying a defect type the request was opened for (read from the existing `qa_defects` / `approval_blocked_reasons`) |
| **M2e** | **A malformed verifier answer confirmed identity**: `same_person` defaulted to "no mismatches listed", so `{}` or a truncated answer stamped image evidence | `stages/identity._verify_multi_clusters`, `identity_failsafe.verify_multi_clusters` | **Fixed here** (review of PR #389). One strict parser, `identity_evidence.parse_verifier_verdict`: only `"same_person": true` (a JSON boolean) with no mismatched image confirms; a missing / non-boolean field, malformed or out-of-range indices, or `true` plus mismatches is rejected and handled as "could not confirm" |
| **M5e** | **A closure that changed no row was reported as done** | `close_reprocess_requests`, `claim_reprocess` | **Fixed here** (review of PR #389). A status is reported only when the update returned that row, owned by this run, with the new status; otherwise `close_not_applied`. Without a run id nothing is claimed or closed (`close_skipped_no_run_id`); a failed claim write is not a claim |
| **M5d** | **No binding to one athlete and one output hash** | `upsert_qa_reedit_task`, `reprocess_outcomes`, `close_reprocess_requests` | **Fixed.** Migration `20261116_reprocess_repair_evidence.sql` applied to production with approval (5 nullable columns; row counts unchanged). A QA task stores the draft's actions (`target_athlete_key`, versioned JSON, since athlete ids are run-local) and its `content_sha256` (`original_output_sha256`). The repair run finds the athlete as the single row overlapping an original action on the same source (≥30 % of the shorter window) and closes `done` only when that athlete is publishable, free of the requested defect types, and its output hash differs; it writes `repair_attempt_id`, `repair_output_sha256`, `repair_verdict`. Unbound requests keep the source-wide rule, marked `source_wide_legacy` (`pipeline/reprocess_binding.py`, `scripts/test_reprocess_binding_contract.py`) |
| M1 | Admission is the analyzer's word | `performance_reel_policy` | Typed verdict exists (#388); no independent action proof. See §9 |

## 3. Run comparison (43710581656 → 43816344303)

| Measure | Before #388 | After #388 |
|---|---|---|
| Model-layer multi-source clusters | 6 | 6 (identical) |
| Final multi-source clusters passing identity gate | 5, all on the text shortcut | 5, each after an image-verifier call covering every member |
| Publishable reels | 10/14 | 10/14 |
| Withheld | 0151 (QA FAIL), 0094 group, 0112 group (QA FAIL), 0115 | same four; the 0112 group's final QA now PASS but still withheld for PRIMARY_ACTOR_UNCLEAR |
| EDL shots with canonical id | 0/25 | 25/25 (`ev2_`, origin analyzer), 0 duplicates |
| Event ids in QA trace / manifest | — | 0/25 (fixed here) |
| Run quality / business gate | fail / partial | fail / partial |

Improvements: verification now actually runs on images; ids reach the EDL. Regressions: none. Unchanged: every
GT disagreement below.

## 4. Identity verification paths, with proof

`scripts/test_release_safety_invariants_contract.py` (identity section) and the real bootstrap
(`install_pre/post_orchestrator_patches`, verifier resolved to `identity_failsafe`):

| Path | Result under the production wrappers |
|---|---|
| Bare `_visual_verified` flag, two sources | `kept_together_unconfirmed` → `IDENTITY_UNCONFIRMED`, not publishable |
| Same tracker id in two sources | `kept_together_unconfirmed`, reason `same_track_id_across_sources_is_not_evidence` |
| Verifier with no thumbnails | split, nothing verified |
| Evidence for 2 members, cluster grows to 3 | not covered, not passed |
| Verified athlete, same or different tracker ids | passes on its image evidence |
| Two people of one source | split |
| Missing source / missing tracks | not passed |
| A~B, B~C, A/C conflict, all 6 orders | split into 3 |
| Verifier answers `{}`, `{"mismatched_indices": []}`, `null` / `"true"` / `1` for `same_person`, a list, `true` with a mismatch, string or out-of-range indices (both verifiers) | nothing stamped, not passed (I6) |

## 5. Event ids

Unique within a run (registry + counter), stable across a window change, a re-run and a rename of the same
bytes, different for two files with one name; present in the EDL (run 43816344303: 25/25), now in the trace and
manifest; a reel missing one or repeating one is not publishable.

## 6. QA lifecycle

Production backlog (read-only, 2026-11-16): 185 `qa_blocked` (all `attempt_count=0`), 13 `cancelled`,
3 `source_not_found`, 1 `done`. Nothing was closed or changed. Requests now: claimed atomically, closed only by
their run, `done` only against their own defect and, for tasks the QA gate creates from now on, only for their own
athlete and a changed output (M5d); every closure records its verdict in `repair_verdict`. Limits: the 202 existing
rows have no binding and keep the source-wide rule; operator requests created outside the QA gate have none either;
two athletes acting in the same window of one source make the match ambiguous, so the request stays unverified. A
request whose closing write fails stays `queued` and is not re-fetched (only `pending` is fetched) — it needs an
operator retry, which the operator API provides.

## 7. Publication-gate bypass

The approval API (`web-api/src/lib/draft-publishability.ts::requireAuthoritativeDraftPublishability`) refuses a
missing row, a name mismatch, and anything but `publishable && qa_evidence_recorded && PASS && qa_passed &&
no technical issues`. Every pipeline block in this work (QA gate, identity unconfirmed, missing or duplicate
event id, media specs) becomes a technical issue or block reason on that row, so it cannot be approved.

## 8. Tests

- New: `test_release_safety_invariants_contract.py` (red on `main` at I2; lineage and reprocess sections red
  because the behaviour does not exist there), `test_gt_review_package_contract.py`.
- Review follow-up: I6 (verifier answers) and R4 (closure reporting) are red on `b746205` —
  "I6 stages.identity: verifier answer {} was read as an identity confirmation" and
  "R4: re-closing a terminal request was reported as {'r3': 'done'}" — and green after the fix.
  `test_root_cause_fixes_contract.py` asserted `done` from an update that returned no row; its fake now returns
  the updated row and the closure carries a run id.
- Updated fixtures (not checks): four contracts now give their fixture events an `event_uid` and stamp real
  evidence instead of a bare flag.
- 61 of 63 contracts that touch identity, the gate, the uploader, reprocess, orchestrator or bootstrap pass
  locally after the follow-up; the other two need `supervision` / `boto3`, missing here, and fail identically
  without this change.
- 71 identity / gate / EDL / manifest / QA / lifecycle / rescue / draft contracts pass locally. CI: see the PR.
- `test_real_r2_multipart_upload.py` fails locally only for a missing `boto3`; not touched.

## 9. Needs video review (VISUAL_REVIEW_REQUIRED)

`scripts/build_gt_review_package.py` (evaluation only; GT is read from a file, never by the pipeline) on both runs:

| Source | Disagreement | Pipeline state |
|---|---|---|
| 0143 + 0152 | wrong merge: GT has two athletes; the image verifier, shown one contact sheet per member, said same person | **published as one reel** |
| 0097 + 0115 | missed merge: GT has one athlete | 0097 published alone, 0115 withheld |
| 0095 | usability: GT excludes 0–6.32 s (`no_meaningful_action`); analyzer score 9 | **published** |
| 0108 | boundary: GT excludes 6.82–9.23 s (`missing_landing`); rendered 1.0–9.0 s | **published** (inside the 0070 + 0108 reel) |
| 0155 | usability: GT excludes it | inside a withheld reel |
| 0151 | conservative cut kept; 10002→10003 continuation refuted by tracking data | withheld |

Each needs the source frames and the identity contact sheets compared by a person blind to the model's answer.
No filename or catalog label is added to inference.

## 10. Cost, deployment, risks

- Cost: no new model calls. Run 43816344303 identity verification cost about $0.009 (5 Flash calls).
- Deployment: pipeline code only; takes effect on the next run. The migration is not applied.
- **Risk to check on the next run:** a reel whose events lose their id on some path will now be withheld as
  `missing_event_provenance`. Run 43816344303's EDL shows every rendered shot with an analyzer id, so none is
  expected; if one appears, it names the path that drops the id.
- Unresolved: the four withheld reels need review; the three published GT disagreements above are live risks.

## 11. Verdict

- Code: **VERIFIED_READY_FOR_CONTROLLED_PIPELINE_RUN** — every code-verifiable defect found is fixed and
  regression-protected through the production wrappers.
- Release: **BLOCKED_BY_VISUAL_EVIDENCE** — 0143 + 0152 (published, two GT athletes), 0095 and 0108 (published,
  GT excludes) need adjudication on video.
- Release: **BLOCKED_BY_EXTERNAL_APPROVAL** — the controlled run itself. (The repair-evidence migration, M5d, was
  approved and applied on 2026-11-16; its code is in place.)

## 12. Full remediation mandate (PR #390, 2026-11-16)

Traceability for RC-01…RC-10, T01…T15 and GATE-A…H: `docs/evidence/FULL-PIPELINE-IMPLEMENTATION-AUDIT.md`.
Baseline and case evidence: `docs/evidence/CONTROLLED-E2E-QUALIFICATION-REPORT.md`. Blockers:
`docs/plans/REMAINING-BLOCKERS.md`.

Defects of the first PR #390 head (`19aa3d7`), each reproduced against that commit before the fix (`881cb57`):

| Defect | Reproduction on `19aa3d7` | Fix |
|---|---|---|
| P0-A invalid binding → legacy `done` | `target_athlete_key="athlete_A"` → basis `source_wide_legacy`, verified **True** | explicit binding modes; only a valid binding can be `done`; legacy → manual reconciliation |
| P0-B overlap-only matching | another actor's longer action (5–20 s) matched a short original (10–12 s): verified **True** | same source content (sha256) + STRONG/MEDIUM links, track contradictions, ambiguity |
| P0-B name-only matching | same file name, different content: verified **True** | content-addressed source reference required |
| P1-C stale binding | `upsert_qa_reedit_task` skipped empty binding columns (kept the old revision's) | binding or explicit marker always written, CAS on `qa_blocked` |
| P1-D hash proof | any non-original string (e.g. specs digest) accepted as repaired output: verified **True** | `content_sha256_kind="bytes"` required on the linked part, plus QA PASS and publishable |
| P1-E stale queued | no recovery path | `recover_stale_reprocess` (pending/failed_max_attempts under CAS) |

## 13. Verdict (supersedes §11)

- **NOT_READY.** Every code-verifiable requirement of RC-01…RC-10 is implemented and covered by red/green contracts
  through production functions or the real bootstrap; all T01…T15 contracts pass on the final commit
  (`scripts/run_release_matrix.py`). No real video has been processed by this code: GATE-A/C/G wait for an approved
  controlled run, GATE-B/D for visual adjudication, GATE-E/F/H for runtime evidence. PR #390 stays a draft.

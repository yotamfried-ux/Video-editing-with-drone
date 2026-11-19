# Cycle 13 — evidence-backed gap matrix, cold-inference isolation, qualification status (2026-11-19)

**Verdict: NOT production-ready.** Mandatory gates that remain unproven:
- an independent blind holdout (no footage exists);
- a complete cold run (the only one, 44374982006, ran out of budget);
- runtime: a cold run takes about 60 min against a target of about 30 min;
- end and validity quality;
- a cloud proof of isolation.

This cycle closed the code-level inference memory channels (MEM-03, MEM-04, MEM-06) and evaluated the one real cold
run in a separate evaluator.

**Evidence classes used:** IMPLEMENTED_UNVERIFIED, SIMULATION_VERIFIED, REAL_RUN_VERIFIED, BLIND_HOLDOUT_VERIFIED,
PRODUCTION_QUALIFIED, BLOCKED.
- A merged PR or a green mock is never closure.
- A familiar-footage cold run is a **cold regression**, not a holdout.

## 1. Sources read and conflicts

**Read:**
- the production spec (`2026-11-14-gap-assessment-and-spec.md`), including the owner's binding no-memory addendum
  (PR #401);
- `PIPELINE-QUALITY-GAP-REGISTER.md` §1–16;
- the GT and identity remediation plan (2026-11-15);
- `MULTI-SPORT-PERFORMANCE-ENGINE.md`;
- the cycle-7 to cycle-12 reports;
- PR #399 (cold experiment) and PR #401 (strict cold-inference workflows);
- the runtime paths (bootstrap, orchestrator, stages, integrations);
- Engineering-OS `mcp-video-analyzer.md` and `external-skills/watch-video`.

**Conflicts recorded (not resolved by picking the easiest reading):**

| Conflict | Documents | Status |
|---|---|---|
| Operator reprocess notes are a product feature (`orchestrator._handle_reprocess_requests`, spec §repair) but are "historical correction logs" under the 2026-11-19 no-memory addendum | spec vs addendum | Strict mode closes the notes channel. Whether production keeps operator-directed re-edits as a separate, labelled mode is an **owner decision**. |
| The runtime target "about 30 min normal workload" vs runs that were only measured warm (cache-assisted, 29 min) | spec vs no-memory addendum, which forbids that cache | The target applies to cold runs. It is unmet (§4). |
| Cycle-12 PA-03 reading (prone from 15.5 s, end ~15.2 s) | cycle-12 evidence vs EVD-13-005 | **Corrected:** the mapping was exact, but the cycle-12 frames stopped at 17.5 s. He stands again and rides 19.0–21.5 s, so if whitewater riding counts the action ends ~21.5 s. (A 22.9 s reel first taken for 0094 was 0142.) |

## 2. Stage matrix

| Stage | Implementation | Required | Remaining gap | Tests | Real evidence | State | Next action |
|---|---|---|---|---|---|---|---|
| Source ingest / preprocessing | `source_uploads`, R2 raw, single-decode proxy | verified bytes, provenance | none known | upload/batch contracts | cold run: 24 sources seeded with identical SHA-256 | REAL_RUN_VERIFIED | — |
| Perception (YOLO + BoT-SORT) | `perception/runtime`, sidecars | per-run detections, no stale reuse | stale-sidecar reuse closed in strict (M7); serial, 35.5 min cold | perception contracts (2 environment-bound), M7 | cold run: 24 sidecars produced in-run | REAL_RUN_VERIFIED (cold); runtime FAIL | parallelise or batch perception (runtime experiment) |
| Event detection (analyzer) | Gemini session analysis | every usable action, no prior memory | cold: 10 of 24 sources unanalysed at a $0.80 cap; history channels closed in strict | M1–M4, onset contract | warm EXP-11/12: FULL 15/24; cold: 12/24 with 14 sources analysed | REAL_RUN_VERIFIED (warm); cold INCOMPLETE | complete cold run with an analysis/QA budget split |
| Boundaries (start/end) | `action_onset`, window policies | starts and ends within 0.5 s | starts 7 incorrect (warm), 3 (cold, partial); ends: E1 rejected | onset O1–O6 | EXP-11/12 MP4s | REAL_RUN_VERIFIED (starts, development set); ends OPEN | end-state evaluator plus labels (data blocker) |
| Validity (failed attempts) | eligibility, `ride_validity` | invalid actions withheld | only 3 GT negatives | eligibility contracts | — | IMPLEMENTED_UNVERIFIED | ≥ 30 negatives |
| Identity / association | clustering, consensus, owner decisions | no wrong merge; fragmentation measured | cold run never reached identity (budget); 0143+0152 untested cold; owner-rejection precedence fixed | W1–W9, 22 identity contracts | EXP-10/11/12: 0 wrong-identity publishable; cold: 0 wrong identity, split 5 (fail-safe) | REAL_RUN_VERIFIED (warm, development); cold untested | complete cold run |
| Segment selection / dedup | selector, `filter_duplicate_draft_candidates` | no duplicate segments | cold: 333 time-attributed duplicate GT frames (0094 A and tandem windows overlap; different subjects) | gt_scorecard S2 | cold 44374982006 | REAL_RUN_VERIFIED, with a measurement caveat | crop-aware duplicate metric |
| Editing / framing | editor, `quality_preserving_framing` | contain-first, CV-justified crop | tandem reel (contain) shows tiny subjects and another athlete for ~13 s (QA-flagged, withheld) | framing contracts, F6 | EVD-13-004 sheets | REAL_RUN_VERIFIED (defect found) | subject-size rule for contain framing (owner: framing policy) |
| Render | FFmpeg | H.264 9:16 30 fps, no black or freeze | serial, 23.7 min cold | real-mp4 render CI | 15 cold reels clean (EVD-13-004) | REAL_RUN_VERIFIED; runtime FAIL | render parallelism experiment |
| QA | qa_gate, source evidence | verdict for every part | cold: QA never ran (budget) | QA contracts | warm: QA false pass 1 (non-GT person), 0 in GT cohort | REAL_RUN_VERIFIED (warm); cold INCOMPLETE | budget split (MEM-04, done in code) |
| Run verdict | `write_batch_qualification` | an incomplete run never reads SUCCESS | fixed: refusals → INCOMPLETE / INCOMPLETE_QA | B5, B6 (replay of 44374982006) | 44374982006 replay | SIMULATION_VERIFIED (replay of real artifacts) | confirm on the next real run |
| Retry / recovery | draft ledger, Gate A | no duplicates, no loss | long-video and staged paths still on legacy naming | D1–D10 | Gate A 44269495332 (real R2) | REAL_RUN_VERIFIED | — |
| Publication | operator-only approval, delivery | no auto-publish | — | U5, release contracts | production fingerprint identical in every qualification run | REAL_RUN_VERIFIED | — |
| **Inference isolation** | PR #401 + `inference_memory_policy` | no video-specific memory or GT in inference | cloud proof of the isolation report; DB-role least privilege | M1–M9, cold-inference contract, S1–S5 | none yet with this patch | SIMULATION_VERIFIED (negative controls) | real strict run; inference DB role (owner) |
| Runtime | — | about 30 min normal workload, cold | cold 60.2 min pipeline (14 analyses only); warm 29.2 min | — | stage timings (EVD-13-003) | FAIL (measured) | profile-driven parallelism experiment |
| Generalisation | holdout tooling (H1–H7) | untouched holdout | no footage | H1–H7 | — | BLOCKED (footage) | new footage + labels |

## 3. Cold run 44374982006 — independent evaluation (EVD-13-001/002/004)

**Run:** owner-launched, PR #399, cap $0.80.

**Frozen inputs to the evaluator:**

| Artifact | SHA-256 | Note |
|---|---|---|
| Diagnostics zip | `ed300335…fcc4` | matches the GitHub digest |
| Reels zip | `84fb859d…5fcd` | matches the GitHub digest |

**Execution:**
- Cost: $0.7542 over 15 calls.
- Analysis: 14 of 24 sources analysed. 42 model calls were refused by the budget (10 analysis, identity and QA).
- Production fingerprint: identical.

| Metric (GT-v1, same scorer) | EXP-11-001 warm | EXP-12-001 warm | Cold 44374982006 |
|---|---:|---:|---:|
| FULL rides | 15/24 | 15/24 | 12/24 (only 14 sources analysed) |
| Missing include s | 16.2 | 16.2 | 102.9 |
| Incorrect starts / ends | 7 / 1 | 7 / 1 | 3 / 0 |
| Excluded frames | 999 | 999 | 523 |
| Wrong-actor frames | 54 | 54 | 54 |
| Visible mixed reels | 1 | 1 | 0 |
| Publishable wrong identity | 0 | 0 | 0 |
| Split athletes | 2 | 1 | 5 (no identity stage ran: fail-safe) |
| Duplicate GT frames (time-attributed) | 0 | 0 | 333 (0094 A vs tandem windows) |
| Publishable / correct | 5 / 4 | 4 / 3 | 0 / 0 (no QA ran) |
| Run verdict recorded | — | — | SUCCESS / FAIL. **Wrong:** a replay with the cycle-13 code gives INCOMPLETE / INCOMPLETE_QA |

**Reading:**
- Cold inference produced no identity or safety error.
- Coverage on the 14 analysed sources is comparable to the warm runs: the 12 FULL rides all come from analysed
  sources.
- The run cannot judge quality because the budget starved analysis, identity and QA (MEM-04).

**MP4 inspection** (`scripts/inspect_reel.py`; sheets viewed):
- All 15 reels: H.264 2160×3840, 30 fps, 0 decode errors, no black or freeze.
- 0094-A reel: one athlete throughout.
- Tandem reel (QA-flagged): contain framing, tiny subjects, another athlete dominant for about 13 s (a framing defect,
  correctly withheld).

## 4. Runtime profile (EVD-13-003, from stage timings of real runs)

| Run | Pipeline wall | Analysis + perception | Perception | Render | QA |
|---|---:|---:|---|---|---|
| Cold 44374982006 | **60.2 min** | 35.5 min (overlapped) | serial: wall = CPU sum, 35.5 min / 24 sources | serial: 23.7 min / 15 reels | 22.5 min wall, overlapped with render |
| Warm EXP-12-001 (forbidden cache) | 29.2 min | 1.4 min | — | 26.6 min / 13 reels | — |

**Bottlenecks:** serial YOLO perception and serial render. A cold run on 24 sources misses the target by about 2×,
even before the 10 missing analyses.

**Root cause:** both stages are CPU-saturated on the 4-vCPU standard runner. This is by design and measured: each
perception producer already uses every core (4K decode plus inference). Earlier runs showed that three concurrent
producers were slower than serial (`perception/runtime._producer_slots`, `SPORTREEL_PERCEPTION_CONCURRENCY=1`). Render
is 4K H.264 encoding under the quality-first 4K output policy. Render cannot start before identity clustering covers
every source, so it cannot overlap perception.

**Options (none adopted):**
1. A larger runner, about 8 vCPU or with a GPU. This is a paid infrastructure decision for the owner. A projection
   from the CPU-bound share puts a cold run at about 30–35 min, but that is a hypothesis to measure.
2. Lower perception stride or decode resolution, or a faster render preset. These carry quality risk and need a
   paired GT experiment; they must not be adopted for speed alone.
3. Caching per-source results is **forbidden** by the no-memory rule. It is the only reason the warm run reached
   29 min.

**State:** runtime is **BLOCKED on an infrastructure decision**, not on code.

## 5. Changes this cycle (PR #402, stacked on #401)

| Gap | Change | Tests | State |
|---|---|---|---|
| MEM-03 history channels | `inference_memory_policy`: closes operator notes, draft feedback, approval history, QA history and identity decisions; stale-sidecar refusal; GT open() audit hook; isolation report | M1–M9 (RED on the #401 head: M1–M5, M9) | SIMULATION_VERIFIED |
| MEM-03 read paths | `INFERENCE-READ-PATH-AUDIT.md` (R1–R14) | — | documented; DB-role least privilege OPEN |
| MEM-04 budget | analysis/downstream reserve; refusal log; INCOMPLETE / INCOMPLETE_QA verdicts | B1–B6 (replay of the real cold run) | SIMULATION_VERIFIED |
| MEM-06 source-specific code | AST guard over runtime strings and prompts | S1–S5 (126 files, 0 violations; planted 4/4 caught) | SIMULATION_VERIFIED |
| Video inspection | `scripts/inspect_reel.py` (metadata, decode, black/freeze, cuts, sheets, bursts, compare) | used on 15 real reels | REAL_RUN_VERIFIED (tool) |

## 6. Experiments

| ID | Commit | Split | Cold | Cost | Result | Decision |
|---|---|---|---|---|---|---|
| EXP-13-COLD-001 (owner) | 1965b368 (run 44374982006) | GT-v1 development (cold regression, **not** a holdout) | caches off, no decisions, isolated namespace | $0.754 | incomplete (budget); 0 identity errors | investigate → MEM-04 fixed in code |
| E-13-REPLAY-B6 | this branch | the same frozen artifacts | evaluator only | $0 | verdict corrected | accept |

## 7. Budget

| Item | Amount |
|---|---:|
| Before this cycle | $1.727 |
| EXP-13-COLD-001 (owner) | $0.754 |
| **Total spent** | **$2.481** of $4 |
| **Remaining** | **$1.519** |

No paid call was made in this cycle: the mandate requires authorization.

A complete cold run on 24 sources, with identity and QA, is estimated at **$1.3–1.6**:
- analysis about $0.054 per source × 24 ≈ $1.30, from the cold run's own analysis calls;
- plus identity and QA ≈ $0.25.

It would therefore need a pre-registered cap of about $1.5 with a downstream reserve of about $0.30, which is nearly
the whole remainder.

## 8. Next actions (priority)

1. **Owner:** merge #401, then #402.
2. **Owner, paid:** authorize one complete strict cold run (cap ≈ $1.5, reserve ≈ $0.30). It is the evidence for
   COLD_INFERENCE_VERIFIED, cold coverage and identity, and the runtime baseline.
3. **Free:** runtime experiment (perception and render parallelism) on CI with no model calls.
4. **Owner:** new footage for the holdout.
5. **Owner:** policy on operator re-edit notes, and an inference DB role without SELECT on history tables.

## 9. The 88-second reel (owner report, 2026-11-19): segment selection and ending

**The reel** (identical in the last four runs, including production run 44388634790) is made of five shots:

| Shot | Rendered | GT | Verdict |
|---|---|---|---|
| 0094 | 2.0–22.5 s | ride 0–13.23 s (green face) | **disputed, not a clear cutting error.** The frames show whitewater riding to 15.0 s, kneeling 15.5–18.5 s, then he **stands again and rides 19.0–21.5 s**. The pipeline's end (22.5 s) is close to the end of the continued action. Whether whitewater riding belongs to the action is the open labelling decision (PA-03). The start is 2.0 s late. |
| 0155 | 0–7.9 s | **exclude: failed take-off** | **selection defect:** 7.9 s of non-action in the reel |
| 0118, 0146, 0142 | full | full | correct |

**Why there is no fix yet** (measured on all 24 sources, EVD-13-005):
- Every candidate signal also hits valid rides:
  - a box that is never upright: 0160, 0165 and the 0094 tandem never stand either;
  - low net displacement: 0140, the tandem;
  - a shrinking box: 0165, 0094.
- The earlier motion-based end rule (E1) cut 31.9 s of real riding.
- Only 3 GT negatives exist, so any threshold would be fitted to the test set.

**Status:** 0155 stays a known selection defect. The reel is a multi-source reel that is not confirmed, so it is withheld
and never auto-published. A fix needs labelled examples of failed attempts and whitewater endings; the holdout
footage request should include them.

# Cycle 14 — Root-cause remediation and qualification status (2026-11-19)

**Branch:** `ccr-3f12fc2f-pdvirt` (PR #402, draft). It is stacked on #401, and #403/#404/#406 are stacked on top of
it.

**`origin/main`:** `90fa08e1`, unchanged in this cycle.

**Spending:** no paid model call, no paid runner, no production write. The budget remainder stays at $1.519.

**Release decision: NOT QUALIFIED.** Pull requests stay in draft. See §8 for the blockers.

## 1. Baseline (Phase A): reproduced from frozen artifacts

**Reference run:** `44388634790`. Pipeline-run #196, on `main` at `90fa08e1`.
- Diagnostics artifact: `sha256:3dbb89a4…eb955`.
- Evaluated after the run with `scripts/gt_scorecard.py` against GT-v1 (ae844a94 / b31fd9b4…27c9).

| Metric | Reference doc | Reproduced |
|---|---:|---:|
| Fully selected rides | 15/24 | 15/24 |
| Recalled FULL in a correct publishable reel | 2/24 | 2/24 |
| Selected excluded frames | 999 | 999 |
| Non-ride windows | 2 | 2 |
| Boundary violations (> 0.5 s) / max | 8 / 2.49 s | 8 / 2.49 s |
| Correct reels withheld | 6 | 6 |

**Not a cold run.** The run log shows 29 analysis-cache hits and 24 perception-sidecar cache hits. Its analyzer
answers are therefore prior-run memory, and it does not count as evidence of cold behaviour (PR #401 rule).

The 999 excluded frames split into three groups:

| Frames | Source | What the pixels show | Class |
|---:|---|---|---|
| 476 | 0155, whole clip, inside the 88 s reel | Failed take-off: prone, then a hands-and-knees pop-up crouch, then a fall at ~7.5 s. The analyzer claimed "pops up, performs a brief turn, and then falls". | **P0 defect, true invalid selection** |
| 379 | 0095, whole clip, **published** | A valid standing ride by a rider who is not catalogued. The catalogued athlete's own take is the GT-excluded one (cycles 7, 10, 12). | **Policy PA-01** (reels for uncatalogued riders): owner decision |
| 144 | 0108 tail, 6.82–9.23 s | Rider still standing and riding down the line at 7.2, 8 and 9 s. GT excludes it as `missing_landing`. | **GT adjudication request.** It conflicts with "never cut genuine riding". |

## 2. Root causes (Phase B) and changes (Phase C/D)

### FIX-PQ-14-001: an action already in progress at the recording start (late starts)

**Evidence.** A replay of the production window code on the frozen sidecars reproduces 25 of 25 rendered windows to
within 0.06 s (`evaluation/boundary_experiment/c14/replay_windows.py`).

Seven of the nine non-FULL rides are late starts. The recording opens mid-paddle or mid-ride and the cut starts
1.0–2.5 s in. Three rules caused this:
1. The analyzer reports starts in whole or half seconds.
2. The source-start snap only fired for starts ≤ 1.0 s.
3. The motion walk-back measured raw on-screen displacement, and was bounded by the analyzer's coarse `setup_start`.

**Why raw displacement fails.** A follow camera makes raw displacement high even for a surfer who is waiting. In 0140
(GT 1.77 s) and 0160 (GT 2.12 s), the surfer reads 0.3–1.5 body heights/s raw before the ride. Any threshold on raw
motion that recovers the late starts therefore breaks these two.

**Change.** Motion is now measured relative to the median of the other people in frame (camera-motion compensated):
`action_onset.relative_motion_per_sec` and `in_progress_from_recording_start`.
- The cut opens at 0 only when every 1 s window from the first frame up to the analyzer start shows at least 1.0
  body heights/s. The threshold comes from the surfing profile (`OnsetPolicy.in_progress_min_relative_motion`); other
  profiles are off.
- Missing evidence, an athlete who appears late, or a waiting phase never move a cut.
- Code: `window_refinement` measures; `complete_action_window_policy.extend_to_recording_start` acts.

**Tests.** `scripts/test_in_progress_start_contract.py`, I1–I9:
- covers a camera pan with a waiting athlete, an athlete who appears late, sparse references, and a dip in motion;
- I8 is a negative control: a raw-displacement implementation fails I2;
- I9 is the frozen-replay non-regression check;
- the suite is RED on the previous code.

**EXP-14-001, paired replay** over 13 frozen runs and 236 events, same evaluator:

| | Before | After |
|---|---:|---:|
| Boundaries improved / worse | — | 24 / 0 |
| Events with a boundary error > 0.5 s | 118 | 98 |

Projected effect on the reference run, from replaying the window starts only:

| | Before | After |
|---|---:|---:|
| FULL | 15 | 17 |
| Recalled-published | 2 | 4 |
| Boundary violations | 8 | 6 |
| Missing seconds | 16.2 | 13.8 |
| Other protected metrics | — | unchanged |

**Evidence class:** `SIMULATION_VERIFIED`.
- Not rendered yet.
- Most warm runs share the same cached analyzer answers, so the replay covers about 3 independent analyzer variants,
  all on development sources.

**Remaining late starts.** 0070, 0094 (A), 0115 and 0152 are not detected at all in the first 0.5–2.5 s: a small or
prone paddler at `imgsz 640` on 4K. 0104 has one window at 0.95. This is a **perception-recall** gap; a boundary rule
can't safely fix it.

### FIX-PQ-14-002 (gate off): observed action validity, an established action rather than a standing-only rule

**Root cause.** 0155 survived every stage on the analyzer's own words: decision path `analyzer_selected →
draft_uploaded`, score 7. RC-03 VALID also accepts "CV activity of the target track", which a surfer carried in a
failed take-off does have.

Free signals do not separate it from valid rides:
- box aspect and displacement (cycles 8 and 13);
- camera-compensated motion (cycle 14): 0155 moves at 1.0–2.6 body heights/s relative to the lineup.

EXP-08-001 failed with a standing-only question: it kept 0155 three times out of three and rejected a valid prone
ride.

**Change: `pipeline/action_validity.py`.**
- The model only reports a per-frame state from the sport profile's vocabulary. For surfing: paddling, popping_up,
  prone_riding, kneeling_riding, standing_riding, in_water, not_visible.
- Code decides:
  - **VALID:** a continuous run of established riding of at least 2 s in every pass. Prone, kneeling and standing all
    count.
  - **INVALID:** only when at least 2 high-confidence passes agree.
  - **Anything else is UNCERTAIN.** UNCERTAIN keeps the shot for review and is never VALID (RC-03 consequence in
    `output_qualification`).
- Profile: `ActionValidityPolicy`.

**Tests.** `scripts/test_action_validity_contract.py`, 19 cases.
- **Negatives:** failed take-off, paddle-only, and a brief pop-up followed by a fall.
- **Hard but valid:** prone, kneeling, whitewater stand–kneel–stand, and riding resumed after a fall.
- **Uncertainty:** disagreement between passes, model outage, unparsable answer, a single pass, low confidence.
- **Negative control:** a standing-only rule would reject the valid prone and kneeling rides.

**Status.** The gate is **OFF** by default (`SPORTREEL_ACTION_VALIDITY`). EXP-14-002 is pre-registered
(`evaluation/ride_validity/PREREGISTRATION-EXP-14-002.md`, cap $0.40) and **needs owner authorization**.

**Evidence class:** `IMPLEMENTED_UNVERIFIED` on real media.

### FIX-PQ-14-003: the identity sheet size is lost on the model-clustering path

**Evidence.** In every warm run since the 6-crop rule (q10p, q12p, 44388634790):
- identity sheets were built with 6 tracked crops (identity_trace: 25 of 25);
- but all 5 of 5 multi-source clusters went to REVIEW `identity_sheet_has_fewer_than_6_crops` without any pairwise
  check;
- each of those review requests had empty pair evidence;
- the decision engine recorded NO_MATCH for all five pairs. That includes four true pairs: 0070+0108, 0094+0118,
  0112+0126 and 0160+0163.

**Root cause.** `_resolve_model_appearance` builds its entry without `sheet_crops`, so model-clustered appearances
carried `_sheet_crops = 0`. Every identity test hand-built appearances with `_sheet_crops: 6`, which is why no test
caught it.

**Change.** Carry `sheet_crops` through that path.

**Test.** `scripts/test_identity_model_path_sheet_contract.py` exercises the production path with the fail-safe
wrapper.
- It is RED on the previous code: sheet size `[0, 0]`, 4 failing.
- It is GREEN now.
- A genuinely thin sheet still stays REVIEW, with no model call.
- All 15 identity contracts pass.

**Effect.**
- Lookalike pairs such as 0143+0152 can now be split.
- True pairs carry pairwise evidence into the owner review request.
- Multi-source clusters still do **not** auto-publish by default (FIX-PQ-10-001, owner policy; unchanged).
- Production runs gain about 2 small model calls per checked pair.

**Evidence class:** `SIMULATION_VERIFIED`.

## 3. Coverage and identity classification (reference run, 24 GT rides)

| Root cause | Rides / reels | Status |
|---|---|---|
| Late start, action already running at frame 0 | 0162, 0097 | **Fixed by FIX-PQ-14-001** (replay) |
| Late start, athlete not detected at the recording start (perception recall) | 0070, 0094 A, 0115, 0152, 0104 (motion 0.95) | Open, perception |
| Premature end: tracker lost the athlete at 5.14 s; no continuation track within 5.9 box heights | 0151 (also withheld: QA `RIDE_BOUNDARY_UNCERTAIN`) | Open, tracking re-identification |
| Attribution of 0094 16.85–27 s: GT gives it to the second athlete; the owner says rider A re-stands at 19–21.5 s | 0094 B (missing 4.49 s), 88 s reel "mixed" by time overlap | **Adjudication** (PA-03), rendered-pixel check |
| Multi-source identity never verified (FIX-PQ-14-003) | 6c84 ×5, 8b1c 0160+0163, 144c 0070+0108, 9524 ×5, 0143+0152 lookalike | Plumbing fixed; publication still owner policy |
| Withheld single-source: rendered tail 1.5 s past the last tracked frame | 0074 (`tail_after_actor_lost_to_recording_end`) | Open (needs a visibility check of the tail) |
| Withheld: QA model `PRIMARY_ACTOR_UNCLEAR` | 0115 | Open |
| Withheld: track gap > 2 s | 0094 B reel | Open |
| Wrong athlete in a published reel | none (published_wrong_identity 0) | — |

## 4. Isolation (MEM) — measured

- **Database: GT is isolated.** The inference credential (`service_role`) has **no USAGE on schema `ground_truth`**
  and SELECT on **0 of 33** GT tables. Those tables include `pipeline_predictions`, `evaluation_runs` and
  `edl_records`. Measured read-only via `pg_catalog` on 2026-11-19.
- **Database: history is not isolated.** `public.draft_feedback` and `public.reprocess_requests` (history channels)
  **are readable**: `service_role` bypasses RLS. Isolation there rests on the strict-mode code closure (cycle 13,
  M1–M9), not on database privileges.
  - **BLOCKER:** a dedicated inference role without SELECT on these tables. That is a production infrastructure change
    and needs the owner.
- **Files:** the path guard (cycle 13) plus PR #403's symlink and traversal canonicalisation.
- **Caches:** the reference run used analysis and perception caches. Strict mode (PR #401) disables them, but no
  completed strict cold run exists yet.

## 5. Runtime

**Reference run (warm):** 40.8 min wall-clock. Summed stage time:

| Stage | Time | Count |
|---|---:|---:|
| Render | 26.3 min | 14 reels |
| QA gate | 11.2 min | — |
| Analysis | 5.5 min | cache hits |
| Perception | 0.6 min | cache hits |

**Cold reference (44374982006):** 60.2 min, with perception at 35.5 min serial and CPU-bound, and render at 23.7 min.

The roughly 30-minute target is not met cold on 4 vCPU. The next step is a larger or GPU runner, which needs
**owner authorization**; no paid infrastructure was used.

## 6. Experiment ledger (cycle 14)

| ID | Hypothesis | Data split | Cost | Result | Decision |
|---|---|---|---:|---|---|
| EXP-14-000 | The reference scorecard reproduces from frozen artifacts | dev | $0 | exact | baseline |
| EXP-14-001 | Camera-compensated motion recovers in-progress starts without pulling waiting into the cut | dev, 13 frozen runs | $0 | 24 better / 0 worse | **accepted** (replay); render pending |
| EXP-14-002 | Observed per-frame states plus a deterministic decision reject 0155 with 0 false rejections of valid rides | dev | ≤ $0.40 | not run | **needs authorization** |
| EXP-14-003 | Model-path identity sheets reach the pairwise verifier | synthetic production path | $0 | RED → GREEN | accepted (plumbing) |

## 7. GT adjudication requests (owner; GT itself not edited)

1. **0108 tail, 6.82–9.23 s.** GT excludes it as `missing_landing`, but the frames show sustained standing riding up
   to the end of the recording. Should it be included?
2. **0094, 13.2–22.5 s.** GT ends rider A at 13.23 s and starts athlete B at 16.85 s. Owner policy says active
   whitewater riding counts, and rider A kneels at 15.5–18.5 s, then re-stands and rides at 19–21.5 s. Which athlete
   is in the track-37 crop, and where does A's ride end?
3. **0095 (PA-01).** Should valid rides by uncatalogued riders produce reels?

## 8. Release gates — status

| Gate | Status |
|---|---|
| CI green on the candidate commit | pending: run on push |
| Negative controls | done: I8, V15, M-RED |
| Isolation | files and GT database PASS; history tables BLOCKED (DB role) |
| Completed real strict cold run | **BLOCKED**: needs authorization (cap ≈ $1.5, reserve ≈ $0.30) |
| GT metrics with no critical defects | **FAIL**: 0155 is unresolved until EXP-14-002; the late-start perception gap; withheld reels |
| Rendered-media confirmation of the fixes | **BLOCKED** on the cold run |
| Blind holdout | **BLIND_HOLDOUT_BLOCKED**: no new labelled footage |
| Runtime ≈ 30 min cold | **BLOCKED**: infrastructure authorization |

**Decision:** keep all PRs in draft and do not merge.
- FIX-PQ-14-001 and FIX-PQ-14-003 are scoped, replay-verified improvements, eligible for merge after a rendered cold
  run.
- FIX-PQ-14-002 stays gated off.

## 9. Cycle 14b — owner review of PR #402 (2026-11-19)

### 9.1 Owner findings, each verified and fixed

| # | Finding | Verified | Fix | Evidence |
|---|---|---|---|---|
| 1 | `action_validity.verify()` never called from production | yes: no caller anywhere | Called from `publishable_reel_policy._qualification_inputs` for every final shot, through `action_validity_runtime.observe_event`. That function cuts target crops from the real video, labels them with their times, makes a budget-checked model call and records the result on the event. Loaded only when `SPORTREEL_ACTION_VALIDITY` is on. | `test_action_validity_media_integration.py`, 12/12: a real ffmpeg MP4 plus sidecar go through the production loader, `_qualification_inputs` and `record_athlete_outcome`. RED without the hook: 0 calls, no observation. |
| 2 | Low confidence could still give VALID | yes: old `decide()` returned VALID for low+low, low+high and medium+low | VALID needs at least 2 agreeing passes, none low-confidence. A single pass is never VALID. | V16–V19; RED on the old `decide()` |
| 3 | 12 crops at 0.5 s from the start could miss the action | yes | Each of two interleaved passes spans the full final window, both edges included, up to 16 crops each. Before any call, the stitched target must be present in ≥ 75 % of samples and at both take-off and ending; otherwise UNCERTAIN with no call. The answer must cover exactly the requested times. | R2, R5–R8 (incl. a wrong-target negative control); V18 |

### 9.2 Editorial policies (evaluation plane; approved GT not edited)

- **0094 frame-by-frame identity.** Checked on real R2 frames every 0.5 s from 11.5 to 24.5 s, with sidecar tracks
  drawn.
  - Track 37, the 88 s reel's crop, is rider 9524ac02 in every frame. The GT-box audit agrees: 195 of 203 frames, 0
    identity switches.
  - He rides standing through whitewater to about 15.0 s, kneels on the carried board 15.5–18.5 s, stands again
    19.0–21.5 s and goes down at about 22.0 s.
  - The GT's second athlete from 16.85 s is a different person (track 154, pink top, green bodyboard).
  - Proposed end of rider A's ride: about 21.5–22.0 s. The pipeline cut at 22.5 s. Filed as ADJ-14-002.
  - The 88 s reel is "mixed" only by time overlap; its pixels show one athlete.
- **0108.** The tail is genuine standing riding. The pipeline preserves it, consistent with policy. The conflicting GT
  label is filed for independent adjudication as ADJ-14-001.
- **0095.** A genuine ride by an uncatalogued rider (POL-14-001).
  - Evaluation side: reported as `uncatalogued_rider`; the published 0095 reel is flagged as a policy violation.
  - Inference side: **BLOCKED.** Inference has no permitted, video-independent signal that a rider is "uncatalogued".
    Athlete registries and follow lists are historical identity data and forbidden in inference. Withholding every
    single-source reel would withhold correct reels.
  - Needed: a permitted current-run input, such as the session's declared athletes, supplied with the upload.
- **`scripts/gt_adjudicated_view.py`** (reference run). The approved-GT metrics stay unchanged, with this breakdown
  next to them:

  | Excluded frames | Item | Status |
  |---:|---|---|
  | 476 | 0155 | Unadjudicated |
  | 144 | 0108 | ADJ-14-001 |
  | 379 | 0095 | POL-14-001 |

  - Mixed reels by pixel: 1 (0143+0152, a real wrong merge), against 2 by time overlap.

### 9.3 Strict no-memory database role (BLK-14-002)

`supabase/migrations/20261119_inference_role.sql` (prepared, **not applied**) creates role `sportreel_inference`:
- It gets exactly the tables inference writes for its own run.
- `draft_feedback` and `reprocess_requests` are explicitly revoked.
- It has no `ground_truth` and no delivery tables.

Supporting changes:
- Strict runs use `SUPABASE_INFERENCE_KEY` when set. Otherwise the isolation report records
  `service_role_fallback_not_isolated`.
- Under the inference key, the reprocess stage is skipped inside inference and must move to a separate pre-step.
- Contract D1–D6, including a negative control.

The SQL has not been executed against a database. Applying it and issuing the key are owner actions.

### 9.4 Free regression and integration tests

- **Local sweep:** 225 `scripts/test_*.py`; 215 pass. The 10 failures fail identically on `main` 90fa08e1 and are
  environment-only (no ultralytics, OpenCV or R2 secrets in this container): background_upload, p0_02,
  perception_contract, real_yolo_tracking, production_upload_api_smoke, raw_permanence_e2e, raw_recovery,
  real_r2_conditional_copy, real_r2_multipart_upload, single_decode_perception.
- **Without PYTHONPATH, as CI runs:** all 90 tests of `performance-reel-contract` and `cost-time-optimizations-check`
  pass, except single_decode_perception (OpenCV).
- **CI regression found and fixed:** `test_publishable_reel_concurrency_contract` hit a module path-load error caused
  by this cycle's hook. Fixed in 6f341495.

### 9.5 Budget (measured) and full-run estimate

- **Remaining:** $1.519, per the registry ledger. No paid call has been made since cycle 13; this cycle's spend is
  $0.000.
- **EXP-14-002:** estimated ≈ $0.30 (54 calls), hard cap $0.40. **Awaiting owner approval.**
- **Strict cold run, all 24 sources** (list-price, from recorded tokens):

  | Component | Estimate | Basis |
  |---|---:|---|
  | Analysis | ≈ $1.29 | cold run: $0.750 for 14 sources, i.e. $0.054 per source |
  | QA and identity cluster check | ≈ $0.21 | warm run 44388634790 |
  | Pairwise identity checks (now actually run, FIX-PQ-14-003) | ≈ $0.20 | ~23 pairs × 2 orders |
  | Singleton merge pass | ≈ $0.19 | EXP-08-002 |
  | Action validity, if enabled | ≈ $0.28 | 25 shots × 2 passes |
  | **Total, with action validity** | **≈ $2.17** | |
  | **Total, without action validity** | **≈ $1.89** | |

- **Proposed cap for the cold run:** $2.30, with a $0.90 downstream reserve.
- **After EXP-14-002**, about $1.12–1.22 would remain. Running the full cold run would therefore need **additional
  authorization of ≈ $1.10**, or deferring action validity (≈ $0.80 more).

### 9.6 EXP-14-002 dry runs: real R2 media, no model, $0

| Run | Code | Windows with both grids | Finding |
|---|---|---|---|
| 44600960800 | 5d6a4573 | 25 / 27 | **0130 `crop_failed`.** Its window runs to the last recorded frame; the final sample seeked past the last decodable frame, and one failed crop voids the grid. That would have withheld a valid ride. Fixed in 54b78db0 (step back before giving up); new real-media test R9 is RED → GREEN. **0151:** the target is lost 1 s before the window ends, so UNCERTAIN, as designed. |
| 44603210495 | 54b78db0 | **26 / 27** (52 grids, 644 crops) | 0130 fixed. 0151 UNCERTAIN by design, with no model call. |

Evidence: `evaluation/ride_validity/exp14_002_dry{1,2}_*.json`, JSON only, no images.

**Paid-run expectation:**
- 52 model calls, ≈ $0.29, cap $0.40.
- 0151 is already one of the at most 2 UNCERTAIN valid windows the pre-registration allows.

**Status:** ready to run. Owner approval of the $0.40 cap is the only remaining step.

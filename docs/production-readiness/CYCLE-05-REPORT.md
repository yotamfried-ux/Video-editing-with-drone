# Cycle 5 — action start/end, six-crop identity sheets, owner REVIEW (PQ-02/03/05/06/17/23/40)

**Owner decisions applied:** (1) keep the paddle-in tied to the wave per GT; 0115's GT start 0.1 s is the target; general mechanism, no per-clip fix; (2) the ride ends with the action (fall / kick-out / exit / wave over), never with tracking continuity; 0108's content after 6.82 s is excluded; (3) six crops per appearance for M2 after a controlled comparison with four; every cross-clip merge needs both-order agreement for EVERY pair, no transitive merge; (4) the owner decides REVIEW; nothing unverified is published; (6) the remaining Gemini budget of the $2 experiment cap, no full pipeline run.
**Gate check first:** CI on the last cycle-4 head (`b9ca26c`) of PR #396 completed green (the skipped checks are skipped by design). **PR #396 stays a draft; not merged; no readiness claim.**
**Status per item:** identity sheet strength — PATCHED · TESTED · REPLAYED (real clusters, production builder); REVIEW requests — PATCHED · TESTED; source-limited start — PATCHED · TESTED · REPLAYED (frozen sidecars, latest run only); Gemini clip verifier for starts/ends — MEASURED, NOT ADOPTED; 0108 end and 0115 start — BLOCKED (below). Nothing is MEDIA_VERIFIED or HOLDOUT_VERIFIED.
**Spend:** cycle 5 ≈ **$0.81** (boundary dev $0.31, 4-crop comparison $0.37, production-sheet cluster check $0.14); cycles 3–5 ≈ **$1.64 of $2** — token-based estimates, not billing data, so the true figure may differ; no more Gemini is planned in this cycle. No pipeline run.

## 1. A finding that changes cycle 4: four crops release 0143+0152
Controlled comparison, same dev pairs, same prompt, M2 only (`evaluation/identity_experiment/cycle5_crops_comparison.json`):

| sheet | false merges | false splits | auto true merges | REVIEW (pos/neg) |
|---|---:|---:|---:|---:|
| 6 crops (cycle 3) | **0** / 60 | 0 | 4 | 5 / 1 |
| **4 crops** | **1** / 59 | 1 | 5 | 3 / 0 |

The false merge is **0143+0152** (MATCH) and the false split is 0097/0115 (NO_MATCH). The pipeline's identity sheet defaulted to **4** crops, so the cycle-4 wiring would have confirmed the 0143+0152 merge in production. Fixed:
- `runtime_quality` default `SPORTREEL_IDENTITY_CROPS` 4 → **6**; the number of crops travels with each appearance (`_sheet_crops`).
- `verify_cluster` and the singleton merge check **refuse** to confirm on a sheet with fewer than 6 crops (→ REVIEW, kept together, unconfirmed). Contract C11 (red-by-construction: 4, 5 and unknown crops, both verifier paths, merge check, gate) is in CI.
- Crop quality is now recorded per appearance (distinct times, span, target size) in the experiment output; selection is evenly spread in time inside the tracked window.

**Real clusters with the PRODUCTION sheet builder** (`pipeline.runtime_quality._identity_sheet`, 6 crops, 2×3; production `verify_cluster`; run 43984350462, $0.14; `cycle5_cluster_check_production_sheet.json`):

| cluster | GT | result |
|---|---|---|
| 0143 + 0152 | **two athletes** | **REVIEW — not released** |
| 0070 + 0108 | same | MATCH |
| 5 sources (0094, 0118, 0155, 0146, 0142) | same athlete (one source is a non-ride) | MATCH (10/10 pairs) |
| 5 sources (A7) | same | REVIEW (6/10 MATCH) |
| 0160 + 0163 | same | REVIEW |

Zero false merges released; 2 of 4 true clusters auto-confirmed, 2 go to the owner. Compared with cycle 4's experiment sheets, two verdicts flipped (0160+0163 MATCH → REVIEW; the A2 cluster REVIEW → MATCH): **verdicts depend on the sheet layout**, so only sheets built by the production builder count as evidence. Per-pair holdout for 4 crops was not run (dev already disqualifies it).

## 2. REVIEW is a structured request, owner-decided
`pipeline/identity_review.py` (+ evidence method `operator_review`): a cluster the consensus cannot confirm stays together, unconfirmed and withheld, and a request is written into the run's identity trace: exact sources (SHA-256 of each video), proposed identity, reason, every pair's decision/features/digests of both model answers, model and prompt digest. The owner decides in `evaluation/identity_reviews/decisions.json` (or `SPORTREEL_IDENTITY_REVIEW_DECISIONS`): an APPROVED/REJECTED record bound to the exact sources (`request_id`), with reviewer and time. A decision never applies to different members or different file bytes, an approval for a source identified only by file name is refused, malformed records are ignored, REJECTED splits the cluster, and nothing in these modules reads or writes the GT or writes a decision (contract `test_identity_review_contract.py`, 6 cases). **REVIEW loses nothing:** on both stored baselines the policy changes only the `publishable` flag of the affected parts — 5 parts on the best run, 0 on the latest — and every selection/window metric is identical (`test_identity_gate_replay_contract.py`, plus the replay on real manifests).

## 3. Action start: a general, guarded rule — "source-limited start"
Root cause, from 24 GT rides: **16 of 24 rides start at 0.0 s** (the recording opens mid-action) and the pipeline's start is 0.5–1.2 s late on most of them, because the analyzer reports start times in whole/half seconds and `refine_event_window` only looks one second before `start`. Rule (`complete_action_window_policy.extend_to_recording_start`, `window_refinement.continuous_presence_from`): if the start is within one analyzer sampling interval (1.0 s) of the recording start and the target track is present from the first frames (≤0.5 s) and unbroken (no hole > 0.4 s) up to that start, the cut opens on frame 0. `output_qualification.action_interval` accepts continuous presence as a valid lead. Nothing else moves; waiting before the paddle-in is not added.

Frozen replay on the latest run (`scripts/boundary_start_replay.py`; production functions on the run's own sidecars and manifest; `cycle5_results.json`):

| | before | after |
|---|---:|---:|
| starts moved | – | 9 |
| rides with start error ≤ 0.5 s | 10 / 24 | **15 / 24** |
| rides FULL (strict scorecard) | 7 | **15** |
| boundaries over 0.5 s (of 48) | 17 | **8** |
| missing seconds | 26.1 | 19.4 |
| excluded frames / non-ride windows / mixed reels / published correct | 999 / 2 / 2 / 4 | unchanged (999 / 2 / 2 / 4) |

0 regressions among the 24 rides. Real negative controls that must not move and did not: 82dd… (GT 1.77 s, track present from 0 — waiting before the paddle-in), 3095fb… (GT 2.12 s), 85aedb… (3.42 s). Synthetic controls (contract `test_source_start_contract.py`, 6 cases, red on `main`): start > 1.0 s, track continuous only from > 0.5 s, a hole in the track, refinement already reports the athlete missing, no measurement, teaser, already at 0, idempotence. Two existing lead-in assertions were updated (0070's catalogued ride starts at 0.0 s).
**Limits, stated plainly:** the rule was designed after looking at all 24 rides, so the dev/holdout split inside this replay (dev 5→8, holdout 5→7 within tolerance) is **not blind**; the independent filming day is the blind test. The best baseline (run 43583126199) cannot be replayed for track-based rules (legacy manifest has no per-event actor tracks): BASELINE_UNVERIFIED for this rule. The 1.0 s window is the analyzer's sampling interval, not tuned to the rides: 2 rides with GT 0.0 s remain late (a1ad…: start 1.2 s; 575a…: track first seen at 0.53 s) and 2 more (5f7ba…: 2.5 s, 207fe…: 1.5 s) are outside the window.

## 4. Start (0115) and end (0108): researched, measured, not solved
- **Research.** Engineering-OS has no temporal-action-localization pattern (only tracking and video-analytics architecture guides). Official Gemini video-understanding docs (Context7): clip offsets, configurable fps, timestamps, ≈100 tokens/s at low resolution. No library detects "paddle-in start" or "ride end" for drone surfing; tracker output is not an action boundary.
- **Measured: Gemini clip verifier** (`scripts/boundary_experiment.py`; target contact sheet + 5-fps clip cut around the pipeline's own candidate; run 43977625921; dev, 14 rides; cost $0.31 ≈ $0.022 and ≈ 28 s per ride; 2 rides skipped by the cost cap): start within 0.5 s on **4/14** (pipeline 3/14), end within 0.5 s on **2/14** (pipeline **11/14**: most rides end with the recording). It reports rounded numbers (15.0, 8.0 …) and once ordered start/end nonsensically. On the three rides where the pipeline's end is wrong it is closer (0108: +2.4 s → +1.18 s) but never within 0.5 s. **Not adopted**; holdout not run (no reason to spend on a rule that fails on dev). Possible use later: a tail *alarm* (verifier end ≥ 2 s earlier than the pipeline's flagged 2 of 3 failing tails with 1 false alarm in 14) routed to REVIEW — not built.
- **Why 0115 and 0108 are still open.** 0115: the analyzer's `setup_start` is 1.0 s and the lead-in is capped at 2.0 s before a 6.5 s start, the target track exists from 1.9 s, GT starts at 0.1 s — no tracker-based rule reaches ≤0.5 s, and widening the cap for every ride would add waiting to rides like 82dd/3095fb (track speed does not separate waiting from paddling: medians 0.46–4.1 body-widths/s overlap between the two groups). 0108: the track is continuous to 9.21 s while GT ends at 6.82 s, so the end must come from action-state evidence, which the tested model does not provide at ≤0.5 s precision. Both need either a better action-state model (e.g. a larger/pro model on short clips, with a budget) or labelled boundary data from the new filming day.

## 5. Protected metrics (frozen replays; evidence level `historical_artifact_replayed`)
| metric | latest run 43920602179 before → after (start rule + REVIEW policy) | best run 43583126199 |
|---|---|---|
| rides FULL / boundaries >0.5 s | 7 → 15 / 17 → 8 | start rule: BASELINE_UNVERIFIED |
| published_correct / wrong identity / non-ride | 4 → 4 / 0 → 0 / 1 → 1 | REVIEW policy: 9 → 6 / 1 → 0 / 2 → 1 (3 correct multi-source reels to REVIEW) |
| correct reels withheld | 6 → 6 | 0 → 3 (pending owner REVIEW) |
| excluded frames, mixed reels, split athletes | unchanged | unchanged |
The recall cost of fail-closed against the best run stays: 3 correct multi-source reels wait for the owner (or a re-verification run).

## 6. Time and cost impact (measured)
Consensus = 2 model calls per cross-source pair per cluster, ≈ 10.5 s per pair (two calls, sequential) on 6-crop sheets, ≈ $0.003 per pair. A 5-source cluster = 10 pairs ≈ 105 s sequentially; the five multi-source clusters of run 43920602179 would add ≈ 4–6 minutes if sequential (not parallelised; not measured end-to-end). The source-start rule costs nothing at run time (a scan of the target track's detections). REVIEW adds no model calls.

## 7. Not verified / remaining
No real pipeline run with the new code; no rendered-media check of any reel; the production wiring was exercised on real clusters but not end-to-end in a run; sheets of 4 crops are refused, but the effect of 6-crop sheets on the clustering stage (other consumers of the thumbnail, run time of `_extract_track_crop`) is untested in a real run; 0115 start and 0108 end open (PQ-05/06); dev/holdout identity results are low-power; operator REVIEW has no UI (a JSON decision file only); PQ-17 partially closed (production-sheet check done on 5 clusters).

## 8. Cycle 6 (free first)
1. Make the consensus calls concurrent and measure end-to-end time on a frozen replay.
2. Tail alarm → REVIEW from the verifier's disagreement (needs a held-out ride set; the new filming day).
3. Start for rides not source-limited (0115 type): evaluate the analyzer's `setup_start` with a larger uncapped lead only where the track is continuous AND a short-clip action model agrees; needs labelled boundaries.
4. Owner REVIEW queue: a small page/CLI to list requests and write decisions.

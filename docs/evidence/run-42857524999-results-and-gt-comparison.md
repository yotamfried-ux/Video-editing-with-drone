# Run 42857524999: results, fixes, and comparison with the manual catalog

Run: `Run Pipeline · a10e8bcb…` on `main@f11de0c` (#357), 2026-11-10, **success**. 44.5 min in total, of which
38 min was "Run pipeline". Every analysis came from the cache (29 sources, `analyze_source` 205 s in total), so
render + QA was almost the whole run.

## 1. Outcome

| | run 42814819534 | run 42857524999 |
|---|---|---|
| conclusion | failure (accountability 0.979) | **success**, accountability 1.0, lineage 1.0 |
| athletes with a reel | 12/12 | 13/13 |
| final QA PASS | 0/12 | **5/13** (published) |
| `RIDE_BOUNDARY_UNCERTAIN` | 11 reels | 0 |
| `DUPLICATE_MOMENT` / out-of-reel findings | 4 reels | 0 |
| remaining QA findings | | `PREMATURE_CUT` on 11 reels (critical on 2), `DEAD_TIME` on 1 |
| LLM cost | $0.75 | $0.20 (analysis cached) |

Stage totals: `render_reels` 1634 s for 13 reels, `qa_gate` 1184 s (overlapping the renders), `analyze_source`
205 s, `yolo_perception` 43 s (the 5 small phone clips only).

## 2. Failures found and fixed in this PR

1. **A real 30 fps reel was rejected as `TECHNICAL_FRAME_RATE_NOT_30FPS`** (0070, "woman in a grey long-sleeved
   top"):
   - Its source-evidence call hit a Gemini 500, so QA fell back to the base tiered QA.
   - That path checks the 4K/30 policy against `analyzer._check_technical_compliance` specs. Those come from
     `integrations.ffmpeg.get_reel_specs`, which had no `fps`; the policy read the missing value as 0.
   - The `quality_preserving_framing` patch only replaced the module attribute, not the name the analyzer had
     already imported.
   - Fix: `get_reel_specs` returns `fps` itself.
   - Test: `scripts/test_qa_fallback_specs_contract.py`, which uses the production bootstrap order. The bug depends
     on import order; the test reproduces "rejected as not 30 fps" on the old code and also checks that a 25 fps
     reel still fails.
2. **Gemini `500 INTERNAL` was not retried.** `_with_retry` only knew 429/503/quota. It now retries
   429/500/502/503/504, `INTERNAL`, `DEADLINE_EXCEEDED` and `ServerError`-type exceptions, but not 400-class client
   errors (same test).
3. **The background disk cleanup made setup slower.** "Wait for runner disk cleanup" waited 196 s, and the
   background `rm` slowed the other steps (ffmpeg install 9 → 29 s, Reset 33 → 69 s). The runner starts with
   **86 GB free**, against ~7 GB of sources plus one intermediate. The cleanup now runs inline and only when less than
   40 GB is free, which skips it on today's image. That saves ~4-6 min against this run and ~2 min against run
   42814819534.

## 3. Comparison with the manual catalog (Supabase `ground_truth`)

Catalog: 24 sources, 45 segments, 14 athletes, all approved, split train 15 / validation 5 / test 4. Pipeline:
final draft window per source and the final athlete clusters from the run's identity trace.

**Time windows** (temporal IoU of the draft window against the athlete's `include` segments):

| split | IoU median | precision | recall | start delta | end delta |
|---|---|---|---|---|---|
| train (15) | 0.77 | 1.00 | 0.81 | +1.6 s | -0.3 s |
| validation (4) | 0.82 | 1.00 | 0.82 | +3.0 s | -1.1 s |
| test (4) | 0.85 | 1.00 | 0.86 | +1.2 s | -0.4 s |

- The pipeline starts later than the catalog (median +1.6 s) and ends a little earlier. Final QA independently
  reports the same early ends (`PREMATURE_CUT`).
- 0095 is catalogued `exclude / no_meaningful_action`, but the pipeline made a reel from it. QA withheld it
  (critical `PREMATURE_CUT`).
- 0108 includes 2.2 s of a segment the catalog excludes as `missing_landing`.
- 0094 has a second catalogued athlete (father and child, 16.9-36.7 s) with no draft. In every source the pipeline
  drafted exactly one person.

**Identity** (pairs of drafted sources sharing an athlete): precision 0.95, recall 0.72.
- Wrong merge: 0143 + 0152.
- Missed merges: 0097 / 0115 (same local surfer) and 0143 / 0146. 0095 is excluded in the catalog anyway.

## 4. Is the pipeline over-fitted to the catalogued videos?

**No leakage was found:**
- No pipeline/integration code reads the `ground_truth` schema or annotation files.
- No source names, durations or catalogued times are hard-coded.
- The pipeline's athlete descriptions are its own (English, other wording), not the catalog's Hebrew labels.
- The studio's suggested boxes come from its own browser tracker following a box the operator drew, not from the
  pipeline's detector. Box agreement would not be circular.
- There is no train > test gap (test IoU 0.85 vs train 0.77).

**But this catalog cannot show that the pipeline generalizes. "Looks very similar to the catalog" mostly measures
the clips, not the pipeline:**
- **A trivial baseline wins.** Predicting "the whole clip" without looking at the video scores median IoU **1.00 /
  mean 0.945**. The pipeline scores 0.81 / 0.78, and "clip minus the first 1.5 s" scores 0.86 / 0.85.
  - Each DJI file is roughly one ride: 18 of 45 segments start at frame 0 and 23 end at the last frame.
  - On this data, agreement in time says almost nothing about whether the pipeline finds the action in long or
    continuous footage.
- **One session, one drone, one sport.** All 24 sources are surfing from 2026-07-20/24, one DJI camera, 3840×2160
  at 59.94 fps. Tests mention surfing in 80 files vs other sports in 18, and four modules
  (`surf_ride_segment`, `wave_completion`, `cut_window_guard`, `surf_editor`) only activate on surf vocabulary.
- **The held-out split is not held out.** All 24 sources, test split included, are the frozen inputs of every
  production run, and every fix in the last runs (including this PR's analysis) looked at their results.
- **One person per clip.** The catalog has 2-3 athletes in 0094 and 0146; the pipeline drafted one per source.
  Crowded sports are where that matters.
- The 5 phone videos in the batch (640-960 px) produced 0 persons, and they are not catalogued, so there is no
  evidence either way about non-drone footage.

**Decisions this PR does on purpose NOT make:** it changes no thresholds, prompts or identity rules to match the
catalog. Tuning the 0143/0152 merge, the 0097/0115 split or the start offset against these 24 clips is exactly the
over-fitting to avoid.

**What would make the evaluation trustworthy** (your call, mostly cataloguing):
1. A truly held-out set: new sessions that are never in a development run, scored only at milestones.
2. Material the current set lacks: long continuous recordings (not one ride per file), other sports, phone and
   ground cameras, several athletes in one frame.
3. Every metric reported next to the whole-clip baseline. A metric that doesn't beat it carries no information.

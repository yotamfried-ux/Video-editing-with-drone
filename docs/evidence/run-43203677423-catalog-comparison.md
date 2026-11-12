# Run 43203677423 against the manual catalog

Run: `Run Pipeline · abf2c288…` on `main@17b5fe4` (#368), 2026-11-12, **success**, 12/13 athletes published,
3 drafts QA-blocked. Compared with the manual catalog (Supabase `ground_truth`, latest approved revision per
source: 24 sources, 45 segments, 16 athletes) as the source of truth. Pipeline side: the final window per drafted
person and the compile clusters, from the run's identity trace and draft-window trace.

`ground_truth.evaluation_runs` is empty: the studio's blind evaluator (`annotation-studio/server/evaluate.mjs`) has
never been run on a pipeline export, although every run writes `predictions.v1.json`. This comparison was done by
hand from the log.

## 1. Time windows

| | value |
|---|---|
| cut seconds that are catalogued `include` for that athlete | **0.91** |
| catalogued `include` seconds of drafted athletes that are in the cut | **0.81** |
| start: cut minus catalogued ride start (22 sources) | median **+1.6 s**, 40.7 s of usable ride starts lost, 0 s early |
| end: cut minus catalogued ride end | median 0.0 s; one outlier, below |

- **Starts are late on almost every ride.** The cut opens on the analyzer's `start` ("stands up", "pops up"). The
  analyzer also reports `setup_start` (the catch and pop-up) on 13 of 22, which matches the catalog (median 0.5 s).
  `window_policy.resolve_window` applied it, but that cut-clip wrapper left the production path when
  `quality_preserving_framing` replaced `editor.cut_clip`; `complete_action_window_policy.extend_to_outcome` restored
  the outcome side only. Fixed here (§3).
- **0094, long-haired surfer: +10.8 s at the end.** Catalog ride 0.0–13.2 s; the father and child ride 16.9–36.7 s
  in the same file. The cut ran 3.5–24.0 s (analyzer: "end 22.5 s: falls into the whitewater"), so 7.1 s of it
  is the tandem ride. Final QA saw riders still going at the end of the clip and reported `PREMATURE_CUT` on the
  athlete; the cut was too long, not too short. Not fixed here.
- 0108: 2.4 s of a catalogued `exclude / missing_landing` segment at the end (the recording-end tail).
- 0095 (`exclude / no_meaningful_action`) got a reel; QA passed it.
- Tandem ride (rescued, 0094): cut 27.8–36.7 s against a catalogued 16.9–36.7 s.

## 2. Identity

Pairs of drafted sources: precision **0.90**, recall **0.75** (excluding 0095, which the catalog excludes).

| pair | error | cause |
|---|---|---|
| 0097 / 0115 | missed merge | "one-piece or wetsuit" read as female swimwear (fixed in #370) |
| 0074 + 0151 | **wrong merge** | `_SAME_COVERAGE` (#360) made a long-sleeved wetsuit top and a full wetsuit compatible, on a reported operator confirmation that the catalog contradicts. Fixed here (§3) |
| 0143 + 0152 | **wrong merge** | the analyzer described both as "on a pink board" (catalog: 0152 rides a white board). Not fixed here |

## 3. Changes in this PR

1. **Lead-in to the catch and pop-up** (`complete_action_window_policy.extend_to_setup`, measured by
   `window_refinement`): the cut opens at `setup_start`, at most 2.0 s before `start` (QA's DEAD_TIME bound), never
   before the athlete's track is first seen, and not at all without that evidence. On this run's catalogued starts:
   usable start seconds lost 40.7 → 21.7, median start gap 1.6 → 0.8 s, 0 s outside the catalogued ride.
2. **0074 and 0151 are two athletes again**: `_SAME_COVERAGE` is empty, so a long-sleeved wetsuit top against a
   full wetsuit is a hard conflict. A stranger in an athlete's reel is worse than a split.

## 4. Not changed, proposed

- 0094: stop a clip where the target stops riding (track motion) or where another drafted subject's action in the
  same file begins; tell final QA which person is the athlete so `PREMATURE_CUT` is judged on them.
- 0151 `PRIMARY_ACTOR_UNCLEAR` (continuity 0.453): measure continuity over the ride only (the catalog ride is
  0–4.8 s of a 7.6 s file; the rest is the wipeout, where the athlete is under water), and re-link track fragments.
- 0143 + 0152: needs a better look at the board; a text rule cannot separate two "pink board" descriptions.
- Run the studio's evaluator on every run's `predictions.v1.json`, so these numbers come from the pipeline itself.

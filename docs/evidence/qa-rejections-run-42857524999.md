# Why final QA rejected 8 of 13 reels in run 42857524999: the reels or the QA?

Method: each QA finding was compared with the manual catalog (Supabase `ground_truth`, independent of QA) and with
each clip's source window, the end of its recording, and the reel's composition. Script and data: run-time
analysis in this PR's conversation; the numbers below are reproducible from the catalog and the run's identity
trace.

## Verdict

**QA was mostly right: the reels ended too early.**
- In the catalogued drone files the ride ends where the recording stops: the catalog's end equals the file's end.
- The pipeline's cut ended **0.2-1.6 s before the end of the recording** on 15 of 22 catalogued sources (e.g. 0118 −1.2 s,
  0074 −1.3 s, 0160 −1.6 s, 0115 −0.9 s, 0104 −0.9 s, 0152 −0.8 s).
- QA's notes describe exactly what was cut: "just before the surfer falls off" (0143/0152), "cut just before its
  natural completion (the fall)" (0115, critical), "rides the whitewater for another second in the original" (0097).

**QA was wrong or unactionable in a few cases:**
- 0130: the clip already ends at the last recorded frame, yet QA says the ride "continues for a few more seconds in
  the source".
- 0126, 0162, 0165: the clip ends at the recording end; a ride still going there was cut by the camera, not the
  edit.

**One real pipeline defect is not addressed here:**
- 0094's window (3.5-22.5 s) runs past the catalogued end of that athlete's ride (13.2 s) into another athlete's ride
  (16.9 s+). QA's `DEAD_TIME` and the run's `mixed_subject` alert both point at it.
- It needs a primary-actor or track fix, not a window rule.

**Content limits:**
- Several single-clip reels score 35-55 on engagement (pacing, payoff) with only minor defects.
- A single 6-9 s ride is what the source contains.

## Root cause in the pipeline

- Clip ends come straight from the analyzer's `end`: the trace shows the final window equal to the analyzer's
  original.
- The analyzer is told to stop at the last readable second without follow-through, and at 4 fps sampling it marks
  the end slightly before the outcome completes.
- The `window_policy` and `cut_window_guard` cut-clip wrappers, which were meant to adjust tails, are not on the
  production path. `quality_preserving_framing.install()` replaces `editor.cut_clip`, so the production chain is
  `complete_action_window_policy` → `quality_cut_clip`. Left as is here: re-enabling them would bring back the 11 s
  pacing cap, which would cut longer rides.

## Fix

**`complete_action_window_policy.extend_to_recording_end`:** an action whose end is within **2.0 s** of the end of
the recording runs to the end.
- The 2.0 s is final QA's own DEAD_TIME definition ("more than ~2 seconds with no meaningful action"), not a value
  fitted to the catalog. The extension therefore can't add what QA calls dead time.
- It applies to every sport, is not applied to teasers, and is not applied when window refinement moved the end to
  where the athlete's track was lost.
- The same normalization feeds the renderer and `_events_out`, so QA and the identity gates see the window that was
  rendered.

**QA source labels now state where the recording ends.** When the draft already uses a window up to the last
recorded frame, the label says a ride still going there was cut by the camera, to be reported at most as a minor
`PREMATURE_CUT`.

**Tests:**
- `scripts/test_recording_end_tail_contract.py` drives the bootstrap stack and `compile_multi_source_reel` with
  real ffmpeg. It reproduces 0115 (6.5-15.5 s in a 16.4 s file); the old code fails with "got [15.5]".
- `scripts/test_qa_evidence_video_labels_contract.py` now checks the recording end in the label.

## Effect, measured against the catalog (validation, not tuning)

| split | IoU median before → after | end delta median before → after |
|---|---|---|
| train | 0.792 → 0.829 | −0.30 → 0.00 s |
| validation | 0.820 → 0.850 | −1.05 → 0.00 s |
| test | 0.852 → **0.889** | −0.35 → 0.00 s |

18 of 23 drafted clips are extended. The cost is +0.7 s inside a segment the catalog excludes (0108,
`missing_landing`).

Not changed:
- the late starts (+1.6 s median); QA does not flag them, and the analyzer deliberately starts at the pop-up;
- engagement thresholds;
- the prompts.

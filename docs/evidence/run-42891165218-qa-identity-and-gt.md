# Run 42891165218: QA findings, the split surfer, and the comparison with the manual catalog

Run: `Run Pipeline · 3de76e29…` on `main@45fd944` (#362), 2026-11-10, **success**, 50 min. All 24 drone analyses
came from the cache; LLM cost $0.20. 12 athletes got a reel, 7 were published, 5 were withheld by final QA.

Sources of evidence: the run's job log (stage timings, QA lines, `DIAG` sections, `IDTRACE_JSON`) and the manual
catalog in Supabase `ground_truth` (read-only, used for validation only). No source video or sidecar was available
to this analysis, so anything that needs pixels or detections is marked as not verified.

## 1. What final QA said, and whether it was right

Every one of the 12 reels carried `PREMATURE_CUT`, 22 findings in total. `PREMATURE_CUT` is always blocking in
`pipeline.qa_gate_policy`, so all 12 drafts were "QA failed · re-edit required / Approval blocked", including the
7 that passed.

| | findings |
|---|---|
| QA's own note says the camera stopped recording ("not an editing choice") | 19 |
| a cut with footage left after it | 3 (0151 @5 s, 0094 @38 s of its reel, 0160 @6 s) |

Checked against the draft windows: 20 of the 23 clips end on the last recorded frame of their file. For those the
re-edit the app offers cannot change anything (the pipeline already skips it as a no-op).

The 5 withheld reels failed on the engagement score (45-55, below the threshold of 60), not on a critical defect.
The weak dimensions were payoff and loopability on all five, pacing on two.

**Root cause.** A fact the pipeline knows exactly (this clip ends where its recording ends) was left to the
reviewer's wording. #359 told the model to report such an ending "at most as a minor PREMATURE_CUT", and the gate
then blocked on the type regardless of severity.

**Fix (`pipeline/source_evidence_runner.py`).**
- Every clip of the draft is measured: place on the draft timeline, source window, end of its recording, and
  whether the window reaches that end. This covers all clips, not only the 4 that get an evidence video (the
  5-clip reel had one clip the reviewer knew nothing about).
- A cut finding on a clip that reaches the end of its recording becomes `RECORDING_ENDS_MID_ACTION`, severity
  `info`, with the reviewer's original type and note kept. It does not fail the reel, block approval or start a
  re-edit.
- A cut finding on a clip with footage left after it is unchanged and still blocks.
- The reviewer cannot hide a real cut behind the new code: `RECORDING_ENDS_MID_ACTION` on a clip with footage
  left is turned back into `PREMATURE_CUT`.
- The reviewer is told these facts per clip, and now returns a per-clip verdict (`opens_on_action`,
  `seconds_to_first_action`, `ending`, `dead_seconds`). The verdicts are stored in the QA result
  (`clip_reviews`) to measure hook, sustained action and endings per clip. They gate nothing.

Effect on this run's findings, recomputed from the log: 19 findings become notes; 3 stay blocking. 9 reels would
no longer be approval-blocked; 3 stay blocked for a real cut (0074+0151, the 4-clip 0094 reel, 0160+0163).
The 5 reels under the engagement threshold still fail on the score; they are no longer blocked for approval.

Test: `scripts/test_qa_recording_limited_contract.py` (fake provider, real ffmpeg). Fails on the old code.

## 2. One surfer, two reels (0097 and 0115)

The catalog has 0097 and 0115 as one athlete ("blue shorts, no shirt, local"). The run made two:
"Person in a dark one-piece or wetsuit on a light blue surfboard" (0097) and "Shirtless man in dark patterned
shorts on a light blue surfboard" (0115). The clustering model separated them itself; the text rules then saw
one-piece against shirtless and kept them apart.

**Root cause.** The identity image the model sees was built to be a contact sheet of the athlete's tracked box at
four moments (`runtime_quality._identity_sheet`), because one crop from one moment is often a back view or a far
shot. In production that never ran:
- `bootstrap` installs `runtime_quality`, then `performance_reel_policy`.
- `performance_reel_policy` replaces `runtime_quality._harden_session_result` with its own version, which builds a
  single 640 px crop around one crop point and records no evidence kind.
- The run's trace shows it: `evidence=crop_point_thumbnailx1` for 23 of 23 persons.
- `scripts/test_identity_trace_contract.py` tested the base function directly, so it passed all along. The bug
  depends on install order.

This is also why the split kept coming back: the contact-sheet fix existed but was not on the production path.

**Fix.** `runtime_quality.attach_identity_image` is the one place that builds the identity image; both hardening
paths call it. The test now installs the two modules in bootstrap order and requires `track_bbox_sheet` evidence;
it fails on the old code.

Not verified: that Gemini merges 0097 and 0115 once it sees four views of each. That needs a pipeline run.
`IDTRACE_JSON` will show `evidence=track_bbox_sheetx4` per person, and the cluster layers show the outcome.

Identity against the catalog in this run (pairs of drafted sources, 0074/0151 counted as one surfer as the
operator confirmed): precision 0.95, recall 0.95. Wrong merge: 0143 + 0152. Missed merge: 0097 / 0115.
The 0143 + 0152 merge is left alone: the pipeline describes both as a pink board, the catalog labels 0152
"white shirt, white board", and without the footage it is not clear which is right.

## 3. Segments: the pipeline's cuts against the catalog

Temporal IoU of each draft window against the catalogued `include` segments of the same athlete, next to the
whole-clip baseline (predict the entire file without looking at it).

| split | n | IoU median / mean | whole-clip baseline median / mean | start delta | end delta |
|---|---|---|---|---|---|
| train | 14 | 0.83 / 0.81 | 1.00 / 0.94 | +1.5 s | 0.0 s |
| validation | 4 | 0.85 / 0.76 | 1.00 / 0.84 | +3.0 s | 0.0 s |
| test | 4 | 0.88 / 0.85 | 1.00 / 0.95 | +1.2 s | 0.0 s |

The pipeline does not beat the whole-clip baseline on this catalog (each file is roughly one ride), so these
numbers describe the cuts; they do not show that the pipeline finds action. The end delta is now 0.0 s (#359).

**Catalogued footage the pipeline left out: 45 s in total.**

| what | sources | cause | status |
|---|---|---|---|
| start 1-3.5 s after the catalogued start | 19 of 22 | The analyzer prompt defines `start` as the pop-up and forbids starting while the athlete paddles. The catalog includes the take-off. | Needs a prompt change, which re-runs Gemini on every source. Not changed. |
| start 6.4 s late | 0115 | The analyzer's `start`; the log has only the final window, so its reasoning is unknown. | Not fixed. The trace now prints the analyzer's timing claims per event. |
| wipeout after the ride, 2.6 s | 0151 | The prompt ends an event when the athlete falls and forbids follow-through. The tail rule only extends ends within 2.0 s of the recording end. | Needs the same prompt change. Not changed. |
| wipeout, 1.6 s | 0160 | Window refinement cut the end where the athlete's track was lost (the fall), 1 s after the last detection. | Not changed: without the sidecar it cannot be told whether the detector lost a visible athlete. The trace now prints track first/last/gaps. |
| second athlete, 19.8 s | 0094 (father and child) | Dropped before clustering as a person with no usable event. | Not fixed; the reason is in the cached analysis, not in the log. |

**Footage in a reel that the catalog excludes or assigns to someone else: 15.5 s, plus one whole reel.**

| what | sources | cause | status |
|---|---|---|---|
| a reel from a source catalogued `exclude / no_meaningful_action` | 0095 (6.3 s, QA PASS 65) | The analyzer scored the ride as usable; final QA agreed. | Not fixed: a judgement of the analyzer, changeable only through its prompt. |
| 9.3 s past the athlete's ride, into another surfer's | 0094 (3.5-22.5 s; the catalogued ride ends at 13.2 s, the next surfer starts at 16.9 s) | The analyzer's `end`; window refinement left it unchanged, so the bound track has detections up to the end. A track id that continues onto another person is one possible explanation. | Not fixed, not verified. `window_refinement` now records the longest gap inside the track and the trace prints it. The run's report flags this reel (`mixed_subject`), but it was published. |
| 2.4 s the catalog excludes as `missing_landing` | 0108 | The recording-end tail rule (#359) extended the cut into it. | Left as is: QA's view and the catalog's differ on this tail. |
| 2.8 s between the ride and the wipeout | 0070 | Not annotated in the catalog either way. | No action. |

## 4. Other changes in this PR

**The analyzer's `outcome_end` reaches the cut for every sport.** The prompt calls `outcome_end` ("where the outcome
fully resolves") a firm claim. `window_policy.resolve_window` applied it, but that wrapper is not on the production
cut path. `complete_action_window_policy.extend_to_outcome` applies it again, clamped to the recording. Surf rides
were already covered (`surf_ride_segment` uses `outcome_end` as the ride end), so this changes nothing in this
run; it matters for jumps, tricks and ball sports.

**The reel closes on a clip whose action resolves, when it ties with the best clip.** `narrative_policy.choose_climax`
picks the best clip to end the reel. When that clip will end on the last recorded frame and another clip within
one analyzer score point ends inside its recording, the second closes the reel and the first opens it. A clearly
better clip stays the closer. Not verified on real reels.

**Trace.** `IDTRACE_JSON` now carries, per event, the analyzer's `llm_start`/`llm_end`, `setup_start`,
`peak_time`, `outcome_end`, its `timing_evidence`, and what window refinement did (status, reasons, first/last
track second, longest track gap). The rows marked "not verified" above can be settled from the next run's log.

## 5. Decisions for the operator

1. **Analyzer prompt: take-off and wipeout.** Moving `start` to the take-off and `end` past the fall would recover
   most of the 45 s. It re-runs Gemini 2.5 Pro on all sources, and an earlier start puts paddling in the opening
   seconds, which final QA scores as a weak hook (`BAD_FIRST_CLIP`). A middle option keeps the start and only
   extends the end through the wipeout.
2. **Engagement threshold on single-ride reels.** A reel that is one 6-10 s ride scores 2-5 on loopability and
   payoff by construction, and 5 reels failed on that alone.
3. **Reel length.** The 4- and 5-clip reels run 55-71 s with 19 s rides; QA marks pacing 4-5 on them. The contract
   today is "every usable wave, complete".
4. **A pipeline run** to verify the identity fix and collect the new trace fields.

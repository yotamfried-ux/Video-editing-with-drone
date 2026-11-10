# Run 42814819534: final-QA failures and the road to ~30 minutes

Run: `Run Pipeline · 1443b545…` on `main@b757a95`, 2026-11-10, 65 min, exit 1. It was the first run after #356 and
is still the newest `pipeline-run.yml` run. The single business-gate failure (0095 `person_B`, accountability
0.979) is fixed by #357; this document covers what that run showed beyond it.

## 1. What the run did

| Phase | Wall | Notes |
|---|---|---|
| Setup steps | 4.6 min | "Free runner disk space" 2m04s; pip 78 s + save 11 s (one-time: #356 changed requirements) |
| Analysis | 24.5 min | 10 uncached 4K sources, `yolo_perception` 120-163 s each, one producer at a time |
| Render + QA | 39 min | `render_reels` 2043 s for 12 reels (245 s of reel), `qa_gate` 1829 s overlapping it |

Stage totals (DIAG): `analyze_source` 3661 s, `render_reels` 2043 s (max 469 s), `qa_gate` 1829 s (max 499 s),
`yolo_perception` 1234 s, `gemini_native_analysis` 263 s. No analysis failures, 12/12 athletes with a reel.
The `🔬 Perception breakdown` line only exists from #357 on, so it is not in this run. The local breakdown is in §3.

Publishable gate: `passed=False errors=4 mode=partial published_athletes=0/12`. The 4 errors all come from
0095 `person_B` (fixed in #357). All 12 reels were also withheld by final QA (`final_qa_failed`); partial mode
does not fail the run on that.

## 2. Why every reel failed final QA

Of the 12 reels, 11 carried `RIDE_BOUNDARY_UNCERTAIN`. Several findings point at moments the reel does not
contain.

### 2a. `RIDE_BOUNDARY_UNCERTAIN` was raised by the pipeline, not by Gemini

`pipeline/surf_ride_segment._merge_group` raises it (critical, blocking) for every ride that has no
`ride_end`/`outcome_end`/`landing_time`/`exit_time`/`kickout_time`, including single-fragment rides.
`source_evidence_runner._context_defects` forwards it to QA as a blocking defect.

The analyzer contract says the opposite (`pipeline/stages/analyzer.py`):
- `end` is "the LAST second the action is still readable (the ride finishes, the athlete falls, the wave
  closes out)";
- `timing_evidence` is REQUIRED and names what is visible at `start` and at `end`;
- `outcome_end` must be OMITTED unless it differs from `end`.

`cut_window_guard` already treats such an event (`timing_precise`) as exact and refuses to pad it. So one module
called the end exact and another called it missing. The analysis cache key includes the full prompt, so the cached
responses in this run were also produced under the `timing_evidence` contract (added 2026-11-01).

**Fix.** A ride end counts as evidence-backed when the fragment that defines the merged ride's end has
`timing_precise` plus non-empty `timing_evidence`. The ride gets `ride_end` with
`ride_end_evidence="timing_evidence"`. The end stays uncertain (blocking) when:
- there is no evidence (legacy responses);
- `window_refinement` moved `end` to the point where the track was lost;
- the end is tail padding;
- only an earlier fragment had evidence.

Test: `scripts/test_ride_boundary_evidence_contract.py` (fails on the old code with the production symptom). The
bootstrap simulation `scripts/test_single_pass_pipeline_simulation.py` now checks both kinds of events end to end.

### 2b. QA read the source-evidence videos as part of the reel

`with_source_evidence` sent `[draft, source_1, …, source_n, prompt]` with one closing sentence: "Additional
videos after the draft are original source windows". The findings show the model read one continuous video:

| Reel length | Finding | What it really is |
|---|---|---|
| 5.0 s | `IDENTITY_MISMATCH @4s`: "transitions to a wider shot featuring three different surfers"; `PREMATURE_CUT @7s` | the un-cropped source window |
| 5.9 s | `LOW_QUALITY @5s`: "0:05-0:10 contains a clip not accounted for in source_windows" | the source window |
| 52.6 s | `DUPLICATE_MOMENT` @52/@58/@67 s: "duplicated, only reframed" | the reel compared against its own source windows |

**Fix.** Each video is preceded by a label:
- `VIDEO 1 of N - THE FINAL DRAFT REEL (5.0s long) … the ONLY video you score; at_seconds refer to it`;
- `VIDEO k of N - SOURCE EVIDENCE, NOT PART OF THE REEL`, with the source file, the padded and used windows, the
  draft time the window covers, and for DJI files the camera-clock capture time. It says what to use the video for
  (early cut, same athlete, two clips repeating one moment) and that the draft is expected to contain this
  footage, reframed.

A defect whose `at_seconds` is more than 1 s past the draft's end cannot describe the draft. It is moved to
`out_of_draft_defects` with `discarded_reason="at_seconds_outside_draft"` and logged (`⚪ QA finding outside the
…s draft ignored`). It is kept for review and does not fail the reel. Test:
`scripts/test_qa_evidence_video_labels_contract.py` (fails on the old code: "every uploaded video must be preceded
by a text label").

### 2c. Cross-file "duplicates" are not overlapping drone files

The DJI files in this run are one camera's numbered sequence on one clock (0094 16:03:37, 0095 16:04:31,
0097 16:06:58, 0104 16:11:10, … 0115 16:19:07, … 0151 16:47:34), so two files can never hold the same moment. The
in-draft `DUPLICATE_MOMENT @9s` on the 17.4 s reel pairs 0115 (recorded 16:19:09-16:19:17) with 0097
(16:07:04-16:07:14). Those are two similar waves 12 minutes apart. The new labels give the model this capture
time. The existing pairwise check (`append_pairwise_source_window_overlap_to_report.py`) compares windows of the
same file across drafts and correctly found 0.

### 2d. Still open (not fixed here, need footage)

The `PREMATURE_CUT` findings that fall inside the draft (e.g. 0070 @6s, 0162 @8s), `DEAD_TIME` (0160 @11s: 7 s
of floating after the ride) and the `mixed_subject` alert on one draft are real editing questions. They should be
re-judged on the next run with the labeled QA, because part of the earlier verdicts was the mislabeling.

## 3. Runtime: where the time goes (local benchmark, 4 vCPU)

Synthetic sources: `testsrc2` + temporal noise, HEVC 4K60 at ~100 Mb/s, 20 s. For detection, the same clip with
ultralytics `zidane.jpg`/`bus.jpg` moving across it. Production settings: `yolo11s.pt`, OpenVINO, stride 5.

**Perception (one 20 s source): 117 s**, matching production's 120-163 s per source.

| Part | s | |
|---|---|---|
| single decode | 38.4 | 4K HEVC decode alone 21 s; intermediate encode +6 s; Gemini proxy + QA evidence copy +11 s |
| primary pass | 16.4 | 240 frames @640 |
| escalation | 56.1 | 600 frames @1280 (stride 2): the weak window was the whole clip (`small_distant_athlete`) |
| other | ~6 | model load, SHA, stitching |

Escalation is inference-bound: OpenVINO `infer` is ~82 of ~105 ms per frame and tracker GMC ~11 ms. These are
the same numbers as raw OpenVINO in the same process (64 vs 70 ms), and static vs dynamic shapes are equal. There
is no hidden overhead to remove. Capping the proxy/evidence encodes at 30 fps saved only 2.5 s (38.1 → 35.6 s), so
it was not changed.

**Render (one 17 s, 2-clip follow-crop reel, exact production command): 83 s wall / 294 s CPU.**

| Part | wall | CPU |
|---|---|---|
| decode only | 20.5 s | 76 s |
| + crop/lanczos graph | 25.4 s | 88 s |
| + x264 4K CRF 14 + QA proxy | 83 s | 294 s |
| without the QA proxy output | | 274 s |

The x264 4K encode is ~70% of render CPU. Every production reel sits at the 45 Mb/s VBV cap (e.g. 393.5 MB /
69 s = 45.6 Mb/s). Moving `fps=30` ahead of the scale changes nothing (24.3 vs 25.4 s graph-only). In production
the render took 8.3 s per reel-second against 4.9 s idle. The difference is QA re-decoding 4K alongside, which #357
removes.

## 4. Changes in this PR for runtime

- **Disk cleanup in the background** (`pipeline-run.yml`). The 2m04s `rm -rf` runs while ffmpeg, Python, weights
  and storage preflight are set up. "Wait for runner disk cleanup" blocks before "Run pipeline". Saves
  min(2 min, the other setup steps), about 1-2 min per run.
- **Render timeout scales with the reel**: `max(600, 120 + 15 × reel_sec)`. With the fixed 600 s limit, a reel
  near the 90 s maximum would have timed out at the worst observed rate (8.8 s per reel-second) and fallen back to
  the much slower per-clip path.
- **`SPORTREEL_ESCALATION_STRIDE`** (default unchanged: half the primary stride). It only exists to A/B a sparser
  escalation on Ground-Truth sources.

Test: `scripts/test_runtime_setup_contract.py`.

## 5. Projection and the decisions that remain

Estimate for a run like 42814819534 on the 4-vCPU runner, with #357 and this PR: setup ~2 min + analysis ~24.5
min + render ~20 min (245 s of reel × 4.9 s) + the last QA ~1 min ≈ **45-50 min**, at unchanged quality. On 4 vCPU
at these quality settings the work does not fit in 30 min. These levers would get there; each one is your decision:

| Lever | Measured effect | Quality evidence | Run estimate |
|---|---|---|---|
| A. Deliver 1080×1920 instead of 2160×3840 (the gate requires 4K today) | render 83 → 34 s (CPU 294 → 128 s), ≈2.5× | At delivery size, vs a lossless 1080×1920 render of the same graph: 4K reel downscaled SSIM 0.9493 / 27.18 dB, native 1080 reel 0.9497 / 27.20 dB. The 9:16 crop never has more than 1215 px of real width (≤1080 px at zoom ≥1.125) | ≈36 min |
| B. Escalation at the primary stride (`SPORTREEL_ESCALATION_STRIDE=5`) | perception 117 → 84 s per 20 s source | On the 240 frames both sample: 99.6% of stride-2 boxes matched, median IoU 0.97, confidence delta 0 (1202 vs 1044 boxes there). What is lost is temporal density: 480 frames only stride 2 sees (2968 vs 1202 boxes total, tracks 11→10 vs 9→8). Whether windows/identity suffer needs the blind GT comparison in Annotation Studio (`scripts/ab_perception_decode.py`) | A+B ≈ 29 min |
| C. 8-vCPU runner | CPU-bound stages ≈2× | none needed | ≈27 min (cost decision) |

Not done on purpose: no CRF, preset, rate cap or detection-density default was changed.

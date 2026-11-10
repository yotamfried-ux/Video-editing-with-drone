# Run 42474968394 — why it failed and why it took 2 hours

Run: `Run Pipeline · b3b308cd…` on `main@a7ec4cf`, 2026-11-08, 116 min in "Run pipeline", exit 1.

## 1. Failure: `RuntimeError: unknown render invocation_id: inv_0_f2ec9b9f`

**Cause.** `context_qa_gate` assigns `cluster["invocation_id"] = inv_<n>_<hex>` and calls
`compile_multi_source_reel(..., invocation_id=...)`. The outermost editor wrapper (`teaser_policy_runtime`,
installed after `publishable_reel_policy`) had no `**kwargs`, so the call raised `TypeError` instantly (the log
shows `render_reels took 0.0s` before every real render). An `except TypeError` fallback re-rendered **without**
the ID, so the publishable scope was registered under a generated `render_<hex>` ID. `_finish_cluster` then
handed QA the original `inv_<n>` ID, which was never registered, and QA crashed. The publishable gate therefore
saw 0 reels, so the 15 "unresolved coverage gap" errors were consequences of the crash, not separate defects.

**Fix.**
- `teaser_policy_runtime`, `surf_ride_gate`, `cut_window_guard`: forward `**kwargs`.
- `context_qa_gate`, `source_evidence_patch`: removed the `except TypeError` retries. They hid this bug and
  re-ran a full render or QA (model calls) on any `TypeError`. The base `_qa_gate_with_edit_context` now
  forwards `invocation_id`.
- Regression test `scripts/test_render_invocation_scope_contract.py` drives the real bootstrap install order.
  It fails on the old code with the exact production `TypeError` and passes with the fix.

## 2. Runtime: perception, not Gemini or rendering

Stage totals: `yolo_perception` 18,290 s over 22 calls, and 8 sources timed out at 1,200 s
(`analyze_source` 19,038 s). Gemini analysis took 346 s and rendering 334 s.

The 4K source was fully decoded three times: the primary YOLO pass, the high-res escalation/rescue pass, and
the Gemini proxy encode. The escalation pass also **seeked once per sampled frame**. On long-GOP H.264/HEVC,
each seek re-decodes from the previous keyframe.

Measured on 4 vCPU (same class as the runner), synthetic 4K60 HEVC at 100 Mbps, `yolo11n`:

| Measurement | Value |
|---|---|
| sequential 4K decode | ~35–38 fps (~26–28 ms/frame) |
| seek + read one frame | **1,686 ms** |
| yolo11n 640 / 1280 inference | 25 / 82 ms |
| 20 s clip, old producer | **770 s** (primary 45.6 s, escalation **722.4 s**) |
| 20 s clip, direct 4K + sequential reads | 152.5 s |
| 20 s clip, single decode (this change) | **112.9 s** (+ makes the Gemini proxy, removing another 4K decode) |
| 3 producers in parallel (old ANALYSIS_WORKERS=3 behaviour) | >1,300 s, unfinished (one after another: 345 s) |
| 2 producers in parallel | 383 s (one after another: 230 s) |

**Changes.**
- `pipeline/perception/single_decode.py`: one ffmpeg decode writes a near-lossless (CRF 4, 4:4:4, 51 dB PSNR
  vs lossless) 1280-px intermediate with the identical frame count, plus the Gemini proxy with the analyzer's
  exact settings. Both YOLO passes read the intermediate, and boxes are mapped back to source pixels. Any
  problem (ffmpeg, frame-count mismatch, low disk) falls back to the direct path.
- `scripts/generate_perception_sidecar.py`: escalation/rescue read frames sequentially (same frames, same order).
- `pipeline/stages/analyzer.py`: reuses the pre-made proxy only when its marker matches the exact source file.
- `pipeline/perception/runtime.py`: at most `SPORTREEL_PERCEPTION_CONCURRENCY` (default 1) producers at a time.
  Other analysis workers keep overlapping Gemini network waits. The timeout bounds only the producer itself.

**Quality evidence (same frames, synthetic 4K clip containing real people).**

| Pass | Matched boxes vs old path | Median IoU | Median \|Δconf\| |
|---|---|---|---|
| primary 640 | 98.1% | 0.947 | 0.032 |
| escalation 1280, same windows | 99.9% | 0.965 | 0.023 |
| full producer, common frames | 95.1% | 0.954 | 0.025 |

In every case the new path found slightly **more** boxes.

### OpenVINO CPU runtime (same weights)

`pipeline/perception/cpu_runtime.py` converts the verified `.pt` weights to OpenVINO once (full precision, no
quantization) and caches the result by the weights' SHA-256. Any failure falls back to PyTorch.

| Measurement (4 vCPU) | PyTorch | OpenVINO |
|---|---|---|
| yolo11n inference, 640 / 1280 | 39 / 116 ms | 13 / 30 ms |
| 20 s 4K60 clip, full producer | 113 s | **74–75 s** |
| agreement on identical frames | | 99.5% of boxes matched, median IoU 0.995, median \|Δconf\| 0.004, same 15 tracks |

Batch simulation, production shape (3 analysis workers, real `ensure_sidecar_for_video` + producer, three 20 s
4K60 clips): **234 s wall**. The producers ran one after another (finished at 78 s, 155 s, 234 s) instead of
oversubscribing the CPU. The old code needed 770 s per clip on an idle machine.

## 3. Rendering: one lossy encode per reel

Correction to an earlier note: `_add_loop_bookend` is never called. Each reel was encoded **twice**: every clip
as a lossy 4K x264 file (CRF 12, `-maxrate 45M`), then the whole reel again in `compile_reel` (CRF 14).

**Change.** In production the cut path (`quality_cut_clip`) now returns a *deferred clip*: a render spec
instead of a file. `compile_reel` builds one ffmpeg pass that reads each source window directly
(`expand_single_pass`):
- the clip framing graph is shared with the per-clip path (`_clip_filter_graph`), and the per-clip command is
  byte-identical to before;
- each clip gets exactly `round(duration × 30)` frames (fps + tpad + trim), which `editor._get_duration`
  reports, so the rendered timeline given to QA matches the reel;
- the same 45 Mb/s cap the clips had is kept;
- if the single pass fails, the clips are encoded the old way and compiled (the reel is never lost);
- `QA_CROP_CHECK=true` (per-clip QA needs real files) or `SPORTREEL_SINGLE_PASS_RENDER=0` keep the old path.

3-clip 4K vertical reel, 4 vCPU, synthetic noisy HEVC source. Quality is scored against the same render made
lossless end to end:

| Render | Wall | SSIM | PSNR | Size |
|---|---|---|---|---|
| before (clip encodes + compile) | 112.2 s | 0.833 | 35.2 dB | 351 MB |
| **single pass (production code)** | **71.0 s** | **0.840** | **35.4 dB** | **127 MB** |
| single pass without the 45M cap (not adopted) | 83.1 s | 0.981 | 44.5 dB | 945 MB |

Before = (capped stream) + one more lossy generation, so the capped single pass is equal or better on any
content. The frame count is identical (665).

## Tests and simulations added

| Test | Proves |
|---|---|
| `test_render_invocation_scope_contract.py` | explicit invocation ID survives the real bootstrap stack (fails on old code with the production TypeError) |
| `test_single_decode_perception_contract.py` | one decode, frame-exact intermediate, proxy bound to its exact source, identical frames sequential vs seek |
| `test_single_pass_render_contract.py` | one ffmpeg run per reel, exact timeline, registry cleanup, fallback still yields the reel, opt-outs |
| `test_single_pass_pipeline_simulation.py` | bootstrap stack → `compile_multi_source_reel` → one 4K/30 silent pass, duration = rendered timeline, QA scope activates, EDL written |
| `test_cpu_runtime_contract.py` | cached full-precision OpenVINO conversion, PyTorch fallback on every failure |

## Not proven yet

- **Real footage.** This environment has no access to R2 footage or the Annotation Studio Ground Truth
  (local-first SQLite). Run `scripts/ab_perception_decode.py` on GT-annotated sources, and evaluate the next
  run's `predictions.v1` export with the Studio blind evaluator against the previous run.
- **The 30-minute target on a full cold batch.** Measured per unit on 4 vCPU:
  - perception ≈ 74 s per 20 s 4K60 clip (about half for 30 fps footage, by frame count);
  - rendering ≈ 40% faster per reel.

  With an analysis cache hit (the same batch again), perception is skipped. A fully cold batch of 24 4K60
  sources is projected at about 30 min for perception alone, plus rendering. The next run measures it.
  Remaining CPU levers would cost money or quality: a larger runner, or a lower escalation density.
- Draft-level evidence gaps in that run's quality report (`missing_dropped_reasons`,
  `draft_source_window_metadata_present`, 15 "unresolved coverage gap" clusters, 16
  `selected_by_selector_not_emitted_as_draft`) are computed from drafts. The crash left 0 drafts, so they
  are expected to clear on a successful run, but only that run can confirm it.

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

## Not proven yet / next

- Real footage. This environment has no access to R2 footage or the Annotation Studio Ground Truth (local-first
  SQLite). Before relying on the change, run `scripts/ab_perception_decode.py` on GT-annotated sources and
  evaluate the next run's `predictions.v1` export with the Studio blind evaluator against the previous run.
- The 30-minute target is not yet demonstrated. Perception is projected at roughly 15–20 min for a 22-source
  batch. Rendering (~150–190 s per reel, serial) is the next limit: each reel is encoded three times (clips
  CRF 12 → compile CRF 14 → whole-reel "bookend" re-encode). Folding these into one encode is the next change,
  and it needs its own quality verification.

# Perception layer default-activation decision — 2026-07-16

Status: addendum to `docs/pipeline-quality-audit.md` (PQ-001) and
`docs/audit/runtime-bootstrap-wiring-gap-20260715.md`.

## What this addendum decides

PQ-001's perception foundation (`pipeline/perception/`) is fully built: a real
Ultralytics YOLO + BoT-SORT producer (`pipeline/perception/producer.py`,
`scripts/generate_perception_sidecar.py --backend ultralytics`), a normalized
detection/tracklet schema, and bbox-derived crop math consumed by
`pipeline/runtime_quality.py::_normalize_event_crop()`. `.github/workflows/pipeline-run.yml`
already forwards `SPORTREEL_PERCEPTION_COMMAND`, `SPORTREEL_REQUIRE_PERCEPTION`,
`SPORTREEL_ULTRALYTICS_MODEL`, `SPORTREEL_ULTRALYTICS_TRACKER`, and
`SPORTREEL_ULTRALYTICS_FPS` from repository secrets/vars. What remained
undecided was whether perception should be **required by default** (fail
closed when a video has no usable detections) or stay **opt-in** (silently
skip and fall back to Gemini-only heuristics, per
`pipeline/perception/runtime.py::ensure_sidecar_for_video()`'s current
behavior). This addendum makes that decision explicit instead of leaving it
as a silent default.

## Evidence considered

- **Track fragmentation is unresolved.** The only documented real run using
  this producer (`docs/audit/run-28768826828-roi-repair-plan-20260706.md`,
  2026-07-06) found 205 unique track ids from a single video: median track
  duration ~0.42s, roughly 150 of 205 tracks under 2 seconds. That level of
  fragmentation means the same athlete is likely split across many track
  ids, which would actively undermine — not strengthen — dedup and identity
  reliability if perception evidence were trusted by default. The
  fragmentation-rate/tracker-tuning follow-up that run's own ROI ordering
  calls for (ROI 4 and ROI 5 in that doc) has not landed.
- **No cost/runtime benchmark exists.** `pipeline/perception/producer.py`
  loads a fresh YOLO model per subprocess invocation with no cross-video
  caching, and `.github/workflows/pipeline-run.yml` runs on `ubuntu-latest`
  (CPU-only, no GPU provisioned). `vid_stride`/`imgsz` are already tuned down
  for CPU speed, but no wall-clock or CPU-minute measurement per video has
  ever been recorded.
- **Fail-closed mode is unvalidated.** `SPORTREEL_REQUIRE_PERCEPTION=1` has
  never been exercised in a real production run. Flipping it on by default
  now would convert an entirely unvalidated failure mode into a hard block
  on every future run, the first time it is ever exercised for real.

## Decision

**Keep perception opt-in.** Do not set `SPORTREEL_REQUIRE_PERCEPTION=1` as a
default, and do not change `pipeline/perception/runtime.py`'s existing
skip-when-unset / fail-closed-when-required behavior — that behavior is
correct as written. The gap this addendum closes is that the choice to stay
opt-in was previously implicit (a default nobody had explicitly decided or
recorded), not that the code was wrong.

## Revisit condition

Reconsider flipping to required-by-default only once both of the following
are true:

1. The ROI 4/5 track-fragmentation and tracker-tuning follow-up from
   `docs/audit/run-28768826828-roi-repair-plan-20260706.md` has landed and a
   fresh real run shows materially lower fragmentation (a much smaller ratio
   of tracks under 2 seconds per apparent athlete) than the 2026-07-06 run.
2. A per-video CPU wall-clock/cost measurement exists for the producer on
   the `ubuntu-latest` runner, so `SPORTREEL_REQUIRE_PERCEPTION=1` cannot
   turn an unexpectedly slow or expensive producer into a silent hard block
   on every production pipeline run.

Until both hold, `pipeline/perception/runtime.py`'s current default (skip
silently, degrade to Gemini-only heuristics) remains the correct behavior,
and PQ-003 (bbox-derived crop) and the track-backed portion of REAL-ID-001
stay best-effort rather than guaranteed.

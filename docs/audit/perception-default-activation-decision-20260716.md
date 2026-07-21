# Perception layer default-activation decision — superseded 2026-07-21

Original decision date: 2026-07-16  
Superseded by: `docs/audit/quality-first-4k-perception-and-face-removal-plan-20260721.md`  
Current status: **computer vision is mandatory in production; real-footage tracking validation remains open**

## Supersession notice

This document previously decided to keep the perception producer opt-in because the only documented real run showed severe track fragmentation, no runtime/cost benchmark existed, and fail-closed mode had not been exercised.

That product decision changed explicitly on 2026-07-21:

- every analyzed event must now carry detector/tracker sidecar evidence;
- production sets `SPORTREEL_REQUIRE_PERCEPTION=1`;
- skipped, failed, invalid, or zero-detection sidecars fail the run;
- events without bbox, frame dimensions, and `track_id` fail closed;
- crop/zoom cannot fall back to Gemini hints;
- the default renderer is full-frame `contain`, so weak tracking cannot silently authorize a destructive crop.

Do not use the former opt-in conclusion below as current guidance. It is retained only as historical evidence explaining the risks that the new mandatory policy must measure and close.

## Historical evidence that remains relevant

### Track fragmentation was unresolved

The documented real producer run found 205 unique track IDs from a single video, median track duration of roughly 0.42 seconds, and about 150 of 205 tracks under two seconds. That evidence still means the same athlete may be split into many short tracks.

Mandatory activation does not prove the tracker is good. It turns missing or unusable evidence into an explicit production failure rather than a silent Gemini-only degradation. Track stitching, ID-switch measurement, occlusion recovery, and difficult-footage tuning remain required before product closure.

### Runtime and cost were unmeasured

The Ultralytics producer loads a model per subprocess and GitHub Actions currently uses a CPU runner. The project still needs per-video wall time, CPU minutes, output size, and upload-time measurements for 4K/30 footage.

### Fail-closed mode lacked production evidence

The previous warning remains valid: a mandatory producer can block every run if configuration or tracking quality is weak. Therefore the 2026-07-21 audit requires deterministic tests, preflight diagnostics, production deployment verification, and a real footage run before closure.

## Current implementation decision

The active contract is:

1. `pipeline/perception/runtime.py` remains the sidecar adapter.
2. `pipeline/required_perception_policy.py` forces required mode, provides the first-party Ultralytics/BoT-SORT default command, rejects empty sidecars, and requires event-level track evidence.
3. `.github/workflows/pipeline-run.yml` sets required mode in production.
4. `pipeline/quality_preserving_framing.py` consumes that evidence but defaults to non-destructive contain framing.
5. A tracked crop is allowed only through the necessity and confidence thresholds recorded in the 2026-07-21 audit.

## Closure conditions

Mandatory perception is not considered production-proven until all of the following pass:

- [ ] difficult surfing footage produces usable sidecars for every analyzed action;
- [ ] track fragmentation is materially lower than the historical run;
- [ ] ID switches, lost/reacquired intervals, and canonical athlete duplication are measured;
- [ ] visually similar surfers are not merged;
- [ ] temporary occlusion, distance, spray, and same-wave surfers do not change the featured identity;
- [ ] detector/tracker wall time and Actions cost are recorded;
- [ ] every crop decision is visually reviewed and justified by measured evidence;
- [ ] a missing/invalid perception run fails clearly in GitHub, Supabase, and the operator app.

Until those items pass, the current state is **mandatory by product contract, contract/CI validated, real-footage validation pending**.

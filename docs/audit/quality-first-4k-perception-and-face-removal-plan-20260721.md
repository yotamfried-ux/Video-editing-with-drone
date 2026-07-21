# Quality-first 4K, mandatory perception, and face-recognition removal plan

Date: 2026-07-21  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Status: **implementation in branch; CI, migration application, deployment, and real-footage validation pending**

## 1. Product decisions

1. The production source is 4K at 30 fps. Canonical publishable Parts must remain **2160x3840, 30 fps, silent, H.264 High Profile, progressive, yuv420p, BT.709, MP4 fast-start**.
2. Framing is **quality first**. The default is `contain`: keep the complete source frame inside the vertical 4K canvas. The pipeline may use a blurred background to fill unused canvas space, but the sharp foreground is not cropped.
3. Crop/zoom is an emergency repair, not a style effect. Gemini score, event type, a request for a dramatic close-up, or the presence of other people is never sufficient by itself.
4. A tracked crop is allowed only when measured CV evidence proves that the full-frame version would otherwise be materially unusable.
5. Computer-vision detector/tracker evidence is required for every analyzed event. There is no production fallback to Gemini-only crop or identity hints.
6. App-user face recognition, face-photo enrollment, face embeddings, biometric RPC matching, and automatic `matched_athlete` ownership are removed. Athlete identity inside footage remains a pipeline tracking/Re-ID problem and is not linked to an app user's face.

## 2. Official first-party references

### YouTube / Google — preserve recording frame rate and 4K delivery quality

Source: https://support.google.com/youtube/answer/1722171

Relevant guidance:

- encode and upload using the same frame rate used during recording;
- 2160p SDR at 24/25/30 fps uses a 35-45 Mbps reference bitrate;
- H.264 High Profile, progressive scan, 4:2:0, MP4 fast start, and BT.709 are recommended upload settings.

SportReel decision: source 4K/30 remains 4K/30 through the canonical production render. The renderer uses high-quality intermediate encoding and caps the clip encoder at the 45 Mbps reference ceiling.

### FFmpeg — contain preserves aspect; cover crops

Source: https://ffmpeg.org/ffmpeg-filters.html

Relevant guidance:

- `contain` scales content to fit while preserving aspect ratio and padding;
- `cover` fills the destination while preserving aspect ratio by cropping.

SportReel decision: `contain` is the default. `cover`/tracked crop is permitted only through the necessity gate below.

### Google Cloud Video Intelligence — tracking is instance-level evidence

Sources:

- https://docs.cloud.google.com/video-intelligence/docs/object-tracking
- https://docs.cloud.google.com/video-intelligence/docs/feature-person-detection

Relevant guidance:

- object/person tracking returns time-scoped bounding boxes for individual instances;
- separate instances of the same object class are tracked independently;
- very small objects can be missed.

SportReel decision: crop and identity decisions require track IDs, per-frame/time bounding boxes, confidence, and visibility evidence. Small-subject failure is explicit rather than silently falling back to an LLM point estimate.

### NVIDIA DeepStream — hard tracking conditions require visual and temporal evidence

Sources:

- https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html
- https://docs.nvidia.com/metropolis/deepstream/5.1/dev-guide/text/DS_plugin_gst-nvtracker.html

Relevant guidance:

- trackers assign object IDs and use spatial/temporal evidence; Re-ID can improve reassociation;
- partial occlusion changes bbox position, size, confidence, aspect, and visual appearance and can cause ID switches;
- the documented tracker example uses `minTrackerConfidence: 0.6`.

SportReel decision: `0.60` is the initial product threshold for allowing a destructive tracked crop. It is a conservative starting value to validate, not a universal standard.

## 3. Crop/zoom necessity contract

A Part remains `contain` unless at least one measured condition is true:

- `athlete_unreadably_small`: tracked bbox height is below 6.5% of source height, or bbox area is below 0.25% of the frame;
- `athlete_near_or_beyond_safe_edge`: bbox center is inside the outer 8% of the frame, or measured visible ratio is below 80%;
- `multiple_tracks_with_small_primary_athlete`: more than one tracked person is visible and the primary athlete occupies below 0.6% of the frame.

Even when one condition is true, crop is blocked unless all of these hold:

- `perception_evidence_status == tracker_sidecar`;
- a non-null `track_id` exists;
- a valid bbox and source dimensions exist;
- detector confidence is at least 0.60;
- visible ratio is at least 0.55.

The emergency crop is capped at `1.30x`. For surfing, the target rendered athlete height is 16%, deliberately lower than other sports so the wave, line, and surrounding context remain visible.

If crop appears necessary but evidence is unreliable, the event/run fails closed for repair or operator review. The pipeline does not guess.

## 4. End-to-end implementation checklist

### A. Lock the contract

- [x] Add a quality-first 4K framing policy module.
- [x] Define `contain` as the default for surfing and every other sport.
- [x] Ignore Gemini zoom requests unless the deterministic necessity gate passes.
- [x] Record each framing decision and its measured reason in `framing_decisions.jsonl`.
- [x] Add 2160x3840 and 30 fps to the deterministic publishability gate.
- [ ] Update top-level README product rules after final review confirms the wording.

### B. Preserve source quality

- [x] Produce 2160x3840, 30 fps silent H.264 output.
- [x] Keep the full sharp source frame in default contain mode.
- [x] Use high-quality Lanczos scaling, High Profile, yuv420p, BT.709, and fast start.
- [x] Use CRF 12 intermediates, CRF 14 final compile, slow preset, and a 45 Mbps clip max-rate reference.
- [x] Disable slow-motion in the quality-first clip renderer for 30 fps source footage.
- [ ] Add a generated 4K fixture and use `ffprobe` to prove width, height, fps, silence, codec/profile, pixel format, and color tags.
- [ ] Measure generation loss against source with VMAF/SSIM on contain output and on one emergency-crop fixture.

### C. Make perception mandatory

- [x] Force `SPORTREEL_REQUIRE_PERCEPTION=1` in production workflow and runtime policy.
- [x] Configure a first-party Ultralytics + BoT-SORT default producer.
- [x] Reject skipped, failed, invalid, or zero-detection sidecars.
- [x] Reject analyzed events lacking bbox, track ID, frame dimensions, or tracker-sidecar status.
- [ ] Add a workflow preflight that prints the resolved model/tracker/stride before video processing.
- [ ] Benchmark detector/tracker wall time and CPU minutes per source video.
- [ ] Tune frame stride and image size using difficult surfing footage, not only synthetic fixtures.

### D. Tracking and identity risk closure

- [ ] Re-run the prior footage that produced severe track fragmentation.
- [ ] Record raw track count, stitched track count, median track duration, tracks under two seconds, ID switches, and lost/reacquired intervals.
- [ ] Prove that one surfer is not split into duplicate canonical athletes.
- [ ] Prove that two visually similar surfers are not merged.
- [ ] Prove that temporary occlusion, spray, distance, and same-wave surfers do not switch the featured identity.
- [ ] Block production closure if fragmentation remains high enough to make crop or attribution unreliable.

### E. Remove app-user face recognition

- [x] Delete the Python face matcher and `face_recognition`/dlib dependency.
- [x] Remove face matching and still-frame extraction from Delivery.
- [x] Remove face-photo enrollment from registration.
- [x] Remove Face Recognition controls from Profile.
- [x] Remove the face-matched My Highlights tab/screen.
- [x] Remove biometric fields and RPCs from active TypeScript database contracts.
- [x] Add a migration that drops `face_embedding`, `photo_path`, `matched_athlete`, matching RPCs, and the `athlete-photos` bucket.
- [x] Keep purchase/customer delivery explicit through Discover, Stripe, purchase records, configured client delivery, or share tokens.
- [ ] Apply the destructive migration only after backup/confirmation.
- [ ] Verify no stored face photos or embeddings remain in the live project.
- [ ] Verify registration, login, Discover, checkout, payment email, and support still work without biometric fields.

### F. Deterministic tests and CI

- [ ] Add unit cases for readable surfing -> contain.
- [ ] Add unit cases for tiny stable surfer -> tracked crop.
- [ ] Add negative cases for crop needed but low confidence/visibility -> fail closed.
- [ ] Add a case proving other visible surfers do not trigger crop by themselves.
- [ ] Add a case proving Gemini `zoom`/event-type hints do not override contain.
- [ ] Add static regression checks proving face-recognition code and dependencies are absent.
- [ ] Run Python contract tests.
- [ ] Run mobile type-check and tests.
- [ ] Run web-api type-check/build.
- [ ] Run all affected GitHub Actions workflows on the final head.
- [ ] Resolve every review finding or document fallback self-review.

### G. Deployment and real-footage experiment

- [ ] Merge only after explicit user approval and green final-head checks.
- [ ] Apply and verify `20260721_remove_face_recognition.sql` in Supabase.
- [ ] Deploy current `main` to Vercel.
- [ ] Publish the mobile update through EAS and verify the active update ID.
- [ ] Run the same source footage used for the previous product-quality comparison.
- [ ] Inspect every final Part visually at native resolution.
- [ ] Verify every Part is 2160x3840, 30 fps, silent, and at most 90 seconds.
- [ ] Verify most surfing actions use `contain`; inspect every tracked-crop decision and confirm necessity.
- [ ] Verify no crop is caused only by an LLM hint, event score, or another visible surfer.
- [ ] Verify every eligible athlete and usable wave is accounted for exactly once or has an evidence-backed rejection.
- [ ] Verify GitHub result, Supabase durable run, operator status, manifest, coverage report, QA trace, and final files agree.

## 5. Central risks and closure bars

### Risk 1 — mandatory CV can turn weak tracking into a hard production blocker

Closure bar: difficult real footage completes with usable sidecars, acceptable fragmentation, stable athlete ownership, and measured runtime/cost. A green unit test is not enough.

### Risk 2 — crop necessity thresholds may be too sensitive or too conservative

Closure bar: manual review of every crop decision in at least one representative surfing run; false crop and missed-needed-crop counts are recorded and thresholds are updated from evidence.

### Risk 3 — 4K rendering increases CPU time, storage, transfer time, and failure exposure

Closure bar: record per-stage wall time, output size, upload duration, retries, and total Actions minutes; no silent timeout or downscale is allowed.

### Risk 4 — removing biometric ownership can expose hidden product dependencies

Closure bar: account registration, profile, Discover, checkout, payment confirmation, delivery, download, and support pass without `face_embedding`, `photo_path`, `matched_athlete`, or the face matcher.

### Risk 5 — code/CI success can hide footage-level quality failure

Closure bar: the audit remains open until a real production-style run proves identity continuity, complete action coverage, justified framing decisions, 4K/30 technical compliance, final QA, and status alignment.

## 6. Required production artifacts

- `framing_decisions.jsonl`
- perception sidecars including raw and canonical track diagnostics
- track-fragmentation summary
- `candidate_decision_ledger.json`
- `athlete_coverage_report.json`
- `publishable_reel_manifest.json`
- `publishable_reel_gate_result.json`
- draft decision, source-evidence, and QA traces
- `ffprobe` media-spec report for every Part
- Actions timing/output-size report
- operator status and durable run row snapshot

## 7. Current closure state

Implementation has started and the core policies/removal are present on the working branch. This audit is **not closed**. Remaining closure requirements are deterministic tests, final-head CI/review, destructive migration approval/application, deployment, and real-footage visual evidence.

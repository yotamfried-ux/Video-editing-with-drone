# Pipeline official reference map

Date: 2026-07-04

This document is the repository-local reference map for `docs/pipeline-quality-audit.md`. It records official implementation references for SportReel / D-to-R pipeline quality work so future sessions can continue without relying on chat history.

## Operating rules

- `docs/pipeline-quality-audit.md` remains the source of truth for gaps, order, invariants, and validation.
- This file maps each gap to official examples and documentation.
- A reference is not proof that a fix works. Proof still requires a deterministic contract test, CI, a real pipeline run, draft review, and traceable metadata.
- Use official vendor/project documentation first. Avoid random repos or blog posts as implementation authority.

## Official references

### Google AI Edge / MediaPipe Object Detector

Use for: PQ-001 deterministic perception, PQ-003 bbox crop, PQ-007 frame/time evidence.

References:

- MediaPipe Object Detector Python guide: `https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector/python`
- Official sample repo: `https://github.com/google-ai-edge/mediapipe-samples/tree/main/examples/object_detection/python`
- Official Raspberry Pi sample: `https://github.com/google-ai-edge/mediapipe-samples/tree/main/examples/object_detection/raspberry_pi`

What to copy conceptually:

- Video mode runs on decoded frames with timestamps.
- Detector output provides category/label, score/confidence, and bounding box.
- Configuration includes score thresholding and max results.
- This is the core model for replacing LLM-estimated crop hints with measured bbox evidence.

### Google Cloud Video Intelligence Object Tracking

Use for: PQ-001 tracklets, PQ-002 identity separation, PQ-005 duplicate evidence, PQ-010 diagnostics.

Reference:

- Object tracking guide: `https://cloud.google.com/video-intelligence/docs/object-tracking`

What to copy conceptually:

- Object tracking is different from label detection because it returns individual object instances.
- Each tracked object can contain frame-level bounding boxes, time offsets, segment information, and confidence.
- Multiple objects of the same class remain separate object annotations.
- Our athlete identity layer should follow this principle: track evidence beats text descriptions.

### Roboflow Supervision

Use for: PQ-001 perception schema/adapters, PQ-003 geometry, PQ-005 event fingerprint support.

References:

- Detections core docs: `https://supervision.roboflow.com/latest/detection/core/`
- Project repo: `https://github.com/roboflow/supervision`

What to copy conceptually:

- Normalize around `xyxy`, `confidence`, `class_id`, `tracker_id`, and `data`.
- Keep our `pipeline/perception/supervision_adapter.py` thin and provider-agnostic.
- Do not build production logic directly around a deprecated tracker. If tracking is added, isolate it behind our own adapter.

### Gemini API Video Understanding

Use for: PQ-006 weak moments, PQ-007 timestamp limits, PQ-008 climax policy, PQ-009 QA limits.

Reference:

- Video understanding guide: `https://ai.google.dev/gemini-api/docs/video-understanding`

What to copy conceptually:

- Gemini remains useful for editorial/sports reasoning after perception narrows candidates.
- Gemini can describe videos and answer timestamped questions, but video visual descriptions are sampled at 1 FPS by default.
- Fast action can lose detail at 1 FPS, so Gemini should not be the only source for identity, crop, moment score, or climax selection.

### NVIDIA DeepStream Python sample apps

Use for: PQ-001 video analytics pipeline structure, PQ-004 multi-source thinking, PQ-009 QA metadata, PQ-010 diagnostics.

References:

- Python sample app docs: `https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Python_Sample_Apps.html`
- Official sample repo: `https://github.com/NVIDIA-AI-IOT/deepstream_python_apps`

What to copy conceptually:

- `deepstream-test2` demonstrates detector -> tracker -> secondary classifier -> renderer.
- `deepstream-test3` demonstrates multiple input sources, batching, and stream metadata extraction.
- `deepstream-test4` demonstrates event metadata attached to buffers.
- We should mirror the separation of decode, inference, tracking, metadata, rendering, and upload decisions without adopting DeepStream as a required dependency.

### AWS Rekognition Video Labels

Use for: PQ-001 timestamped detections, PQ-003 bbox crop, PQ-010 metadata schema sanity check.

Reference:

- Detecting labels in video: `https://docs.aws.amazon.com/rekognition/latest/dg/labels-detecting-labels-video.html`

What to copy conceptually:

- Detection results include timestamps, label confidence, instance bounding boxes, and detection confidence.
- Person labels can include multiple bbox instances.
- Our diagnostics should preserve both classification confidence and bbox/detection confidence when available.

## Audit mapping

| Audit item | References | Implementation pattern |
|---|---|---|
| PQ-001 | MediaPipe, Supervision, Google Video Intelligence | Frame/video input -> detection records -> normalized perception/tracklet schema. |
| PQ-002 | Google Video Intelligence, DeepStream, Supervision | Keep athlete identity tied to track/bbox evidence; avoid text-only merges. |
| PQ-003 | MediaPipe, AWS Rekognition, Supervision | Compute crop from measured bbox center and visible ratio. |
| PQ-004 | DeepStream multi-source samples | Keep source and batch identity attached through the pipeline. |
| PQ-005 | Google Video Intelligence, Supervision | Fingerprint events from cropped evidence, trajectory, type, and source window. |
| PQ-006 | Gemini Video Understanding | Enforce weak-moment policy in code; Gemini score is advisory. |
| PQ-007 | MediaPipe timestamps, Google Video Intelligence time offsets, Gemini limits | Store original, clamped, final, and peak/action time evidence. |
| PQ-008 | Gemini limits + perception references | Climax requires editorial score plus perception quality. |
| PQ-009 | DeepStream metadata, Google/AWS response schemas | QA defects must map to event/source/track metadata before upload. |
| PQ-010 | DeepStream metadata, Google Video Intelligence object annotations | Persist a full audit artifact per draft. |

## Minimum future-session sequence

1. Read `docs/pipeline-quality-audit.md`.
2. Read this file.
3. Pick the next open PQ item in the audit order.
4. Open the official references mapped to that PQ item.
5. Inspect the current code paths named in the audit.
6. Add or update a deterministic contract test.
7. Keep production behavior unchanged unless the PR explicitly owns that behavior change.
8. Validate with CI, a real pipeline run, draft review, and metadata before declaring a quality issue solved.

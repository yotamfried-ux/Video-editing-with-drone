# Pipeline state reconciliation — 2026-07-05

Purpose: compare the desired pipeline-quality architecture from the audit files against what is implemented on `main` after PRs #88-#106.

## Bottom line

The project now has many runtime guardrails and deterministic contracts, but it is not yet at full operational reel-quality readiness.

The main gap is architectural: the audit target is perception-first editing, while the current production path is still mostly Gemini/event-first with guardrails around it. Perception schemas exist, but a real production detector/tracker pass is not yet the source of truth for identity, ride boundaries, crop, and event windows.

## What is implemented

- Perception foundation exists: normalized detections, bbox-to-crop metadata, and Supervision adapter contracts.
- Batch/session isolation exists for R2 runs.
- Cross-source and final duplicate guards exist.
- Weak moment filtering, window policy, narrative policy, QA diagnostics, draft diagnostics, context QA, source evidence QA, and surf ride continuity guard exist.
- Surf ride fragments are normalized into `surf_ride` events and uncertain ride/identity evidence is surfaced to QA.

## What is still only partially implemented

### Perception-first production path

Desired: every candidate event should have real detection/track metadata before editing: bbox, confidence, visible ratio, track id, and frame/time evidence.

Actual: `pipeline/perception/*` provides schemas/adapters, but the pipeline still does not run a real detector/tracker over footage as the primary source of candidate events. Many guards consume `track_id` only if it already exists.

Status: partially implemented / foundation only.

### Identity continuity

Desired: no normal draft without stable single-athlete evidence across all events in the ride.

Actual: cross-appearance identity splitting exists, and surf ride uncertainty flags exist, but same-source similar-surfer identity is still not proven by a real tracker unless track data is already present.

Status: partially implemented / fail-closed in some uncertainty cases, but not proven by production CV.

### Ride boundaries

Desired: complete ride segments from takeoff/start to natural finish/outcome.

Actual: surf fragments are merged and missing explicit end becomes `RIDE_BOUNDARY_UNCERTAIN`. This is safer, but the ride end is still inferred from available event fragments unless a detector/source-window pass proves the true end.

Status: implemented as guardrail, not fully solved until real output validates it.

### QA

Desired: QA judges final draft against edit JSON and original source windows.

Actual: context JSON, source clips, and fail-closed behavior exist. If source evidence cannot be visually checked, drafts become review-required. This is a strong safety net, but it still depends on source paths being available and on QA model behavior.

Status: implemented as fail-closed safety net; needs real-run verification.

## What is not validated yet

The audit explicitly requires real pipeline run and draft review before declaring quality solved. The latest real-output evidence that drove these fixes showed remaining issues; there has not yet been a verified successful real run after PR #106.

Required validation:

1. Run pipeline on `main` after PR #106.
2. Inspect generated review drafts in the operator UI.
3. For each draft, inspect metadata/diagnostics for:
   - `ride_segment`
   - `merged_ride_fragments`
   - `RIDE_BOUNDARY_UNCERTAIN`
   - `IDENTITY_UNCERTAIN`
   - `source_evidence_visual_uploaded`
   - `qa_review_required`
4. Confirm no normal draft mixes athletes, repeats the same source window, or cuts a ride before the natural end.

## Remaining priority order

### P0 — Real-run validation after PR #106

Run the pipeline and inspect the actual drafts. Do not perform another deep code fix until there is fresh output from the current `main`.

### P1 — Production detector/tracker integration

Convert the perception foundation into a real production pass that emits detections/tracklets for source videos. This is the biggest remaining gap between desired and actual architecture.

### P2 — Metadata/UI visibility

Ensure the operator UI can show QA/diagnostic details for each draft, not only the video and filename. If the QA agent flags review-required but the operator cannot see why, debugging remains slow.

### P3 — Replace runtime shims with first-class pipeline stages

Many current repairs are runtime hooks/guards. They should eventually be consolidated into explicit stages: perception -> ride segmentation -> identity continuity -> editing -> context/source QA -> upload.

## Decision

Do not mark the audit as complete yet. Mark most recent repairs as implemented by contract/CI, but pending real-run validation. The next operational step is a new pipeline run on `main`, followed by draft + metadata inspection.

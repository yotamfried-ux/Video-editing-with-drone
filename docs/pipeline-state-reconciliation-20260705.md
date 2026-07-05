# Pipeline state reconciliation — 2026-07-05

Purpose: compare the desired pipeline-quality architecture from the audit files against what is implemented on `main` after PRs #88-#106 and after real-run review of run `28749812589`.

## Bottom line

The project now has many runtime guardrails and deterministic contracts, but it is not yet at full operational reel-quality readiness.

The main gap is architectural: the audit target is perception-first editing and learned product-value selection, while the current production path is still mostly Gemini/event-first with guardrails around it. Perception schemas exist, but a real production detector/tracker pass is not yet the source of truth for identity, ride boundaries, crop, event windows, or deciding which moments are worth showing.

## New real-output findings from run 28749812589

The run completed successfully on `main` after PR #106, but operator review still showed product-level failures:

1. The same surfer appears in multiple drafts under different descriptions.
2. A different surfer can appear in the middle of another surfer's clip.
3. Some waves still may not be shown through a satisfying natural finish.
4. Good moments can be dropped, including a surfer giving a high-five during a wave.
5. QA-labelled drafts can still appear with an ordinary `Approve` button in the operator UI.
6. Upload UX must support selecting and uploading multiple raw videos in one action, with parallel upload progress.

## Official references: how larger systems learn what is worth showing

### YouTube recommendations

Official YouTube documentation says recommendations are designed to anticipate and meet user needs and provide relevant, satisfying viewing experiences. It uses viewing behavior, likes, dislikes, subscriptions, feedback, satisfaction surveys, channel reputation, channel quality, and external evaluators.

Reference: `https://www.youtube.com/howyoutubeworks/recommendations/`

Implication for SportReel: We need explicit feedback labels and satisfaction outcomes, not only Gemini's one-time score. Operator actions like Approve, Send to re-edit, Reject, Missing good moment, Wrong athlete, Cut too early, Duplicate athlete, and Bad crop should become training/evaluation signals.

### Netflix artwork personalization

Netflix TechBlog describes selecting the best artwork as a learning/ranking problem. Netflix collects data on which candidate artwork was shown, whether it caused quality engagement, uses contextual bandits, controlled exploration, logging of selection propensities, offline replay evaluation, A/B tests, and avoids learning clickbait by checking quality of engagement.

Reference: `https://netflixtechblog.com/artwork-personalization-c589f074ad76`

Implication for SportReel: Candidate clip selection should be logged like a ranking problem. We need a candidate pool, selected/not selected labels, explicit reasons, and offline replay/evaluation before changing ranking rules. The system should not just pick the top Gemini score.

### Amazon Personalize

Amazon Personalize documentation treats user-item interactions as the training data for recommendations. It records event types such as click, watch, purchase, like, and real-time events. Real-time event tracking keeps recommendations fresh and adapts to current user interests.

References:

- `https://docs.aws.amazon.com/personalize/latest/dg/interactions-datasets.html`
- `https://docs.aws.amazon.com/personalize/latest/dg/recording-events.html`

Implication for SportReel: Every operator interaction with a draft or candidate needs to become an event. Without structured events, the system cannot learn that a high-five during a wave is valuable or that a repeated surfer draft is bad.

### OpenAI evals and graders

OpenAI evals are built by defining the desired behavior, running test inputs, analyzing results, and iterating. Graders can compare output against reference answers or rubrics and return numeric scores, including score-model graders.

References:

- `https://platform.openai.com/docs/guides/evals`
- `https://platform.openai.com/docs/guides/graders`

Implication for SportReel: We need eval datasets and graders for "worth showing" decisions: full wave, social/high-five moment, no mixed athletes, no repeated athlete draft, no early cut, and no false negative removal of good moments.

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

### Identity continuity and people-in-clip leakage

Desired: no normal draft without stable single-athlete evidence across all events in the ride, and no other athlete should appear inside the final clip unless explicitly intentional.

Actual: cross-appearance identity splitting exists, and surf ride uncertainty flags exist, but same-source similar-surfer identity is still not proven by a real tracker unless track data is already present. Real output still showed another surfer entering the middle of a clip.

Status: open / partially guarded.

New gap: `REAL-ID-004 — Same-clip multi-person leakage`.

Target invariant:

```text
A normal single-athlete draft must not contain another visible athlete during the selected ride window unless the clip is explicitly labelled as a multi-person/social interaction and approved by product policy.
```

Required behavior:

1. Detect multiple athlete candidates inside each selected source window.
2. If multiple candidates appear and the moment is not intentionally multi-person, flag `MULTI_PERSON_CLIP` / `IDENTITY_UNCERTAIN`.
3. For social moments, keep the clip only if it is explicitly classified as `SOCIAL_MOMENT` and the main athlete remains clear.
4. Persist the evidence in the candidate decision ledger.

### Ride boundaries and wave completion

Desired: complete ride segments from takeoff/start to natural finish/outcome.

Actual: surf fragments are merged and missing explicit end becomes `RIDE_BOUNDARY_UNCERTAIN`. This is safer, but the ride end is still inferred from available event fragments unless a detector/source-window pass proves the true end. Real output still cannot be declared fully satisfying for every wave.

Status: open / implemented as guardrail only.

New gap: `REAL-WAVE-002 — Wave completion confidence is not measurable`.

Target invariant:

```text
Every surf draft must expose a wave_completion_score and boundary evidence explaining whether the ride was shown from useful start through natural finish.
```

### Value selection / what is worth showing

Desired: model learns product value from operator feedback and examples: exciting rides, social moments, high-fives, clear athlete, full wave, non-duplicate, good crop, and good story arc.

Actual: the system still relies primarily on Gemini event scores plus guardrails. There is no structured feedback loop, candidate ranking dataset, offline replay, or explicit labels for missed good moments.

Status: open.

New gap: `REAL-VALUE-001 — No learned model of what is worth showing`.

Target invariant:

```text
Every candidate moment must be ranked using product-value criteria and operator feedback, not only Gemini score. The system must be able to learn from approved, rejected, re-edit, missing-good-moment, duplicate, wrong-athlete, and cut-too-early examples.
```

Required behavior:

1. Add a candidate decision ledger for every run.
2. Add operator feedback events for each draft/candidate.
3. Define value labels: `FULL_RIDE`, `SOCIAL_MOMENT`, `HIGH_FIVE`, `BIG_TURN`, `FALL`, `GOOD_STYLE`, `CLEAR_ATHLETE`, `BAD_CROP`, `WRONG_ATHLETE`, `DUPLICATE_ATHLETE`, `CUT_TOO_EARLY`, `BORING`, `FALSE_NEGATIVE`.
4. Build an eval set from reviewed runs.
5. Add a grader/ranker that scores candidates against the product-value rubric.
6. Keep exploration/recall: do not drop uncertain but potentially valuable moments without a ledger entry and review path.

### Candidate recall / dropped good moments

Desired: good moments such as high-fives or unusual social interactions should not disappear silently.

Actual: a good high-five/social moment disappeared from the latest run, and there is no artifact explaining whether it was never detected, dropped by score, merged away, blocked by identity, deduped, or removed by QA.

Status: open.

New gap: `REAL-RECALL-001 — Good moments are dropped without trace`.

Target invariant:

```text
Every source moment that was detected as a candidate, merged, dropped, selected, QA-failed, or uploaded must be traceable with a decision reason.
```

### Run-level athlete canonicalization

Desired: the same athlete should not appear as several separate normal drafts under different textual descriptions unless the output is intentionally a multi-ride collection.

Actual: the same surfer still appears across multiple drafts under different clothing/board descriptions.

Status: open.

New gap: `REAL-ATHLETE-001 — No run-level athlete canonicalization`.

Target invariant:

```text
Within a run, each draft must map to a stable `athlete_id`. The same `athlete_id` should not produce multiple normal standalone drafts unless explicitly grouped as a collection.
```

### UI gating for QA/diagnostics

Desired: QA-flagged or review-required drafts should not look like normal approvable drafts.

Actual: screenshots show a draft with `QA_` in the name still displaying the normal `Approve` button.

Status: open.

New gap: `REAL-UI-001 — QA/review-required drafts still show normal approval affordance`.

Target invariant:

```text
If a draft has QA/review-required metadata or a QA-labelled filename, the operator UI must disable or visually demote Approve and show the blocking reason before approval.
```

### Upload UX — multiple videos in parallel

Desired: the upload button should allow selecting multiple videos and uploading them in parallel with per-file progress and a shared batch id.

Actual: the upload API initializes one upload session per request with singular `filename` and `mimeType`. Multi-file upload may still be possible if the frontend sends concurrent requests per file, but the current API shape and 10/hour operator upload rate limit are not batch-friendly.

Status: unverified / likely partial.

New gap: `REAL-UPLOAD-001 — Multi-video parallel upload UX is not proven`.

Target invariant:

```text
The operator can select multiple raw videos at once; the app uploads them concurrently under one batch id, shows per-file progress/errors, and starts the pipeline only for that batch.
```

Required behavior:

1. Confirm the file input supports `multiple`.
2. If not, update the UI input to `multiple` and upload all selected files concurrently.
3. Reuse one `batch_id` across all files in the selection.
4. Show per-file upload progress and failure retry.
5. Adjust or exempt the upload-init rate limit so one multi-file batch does not hit the 10/hour limit unexpectedly.
6. Add a frontend/API contract test for two files uploaded in one batch.

## What is not validated yet

The audit explicitly requires real pipeline run and draft review before declaring quality solved. The latest real-output evidence after PR #106 still shows remaining issues, so the audit must remain open.

Required validation:

1. Run pipeline on `main` after each repair loop.
2. Inspect generated review drafts in the operator UI.
3. For each draft, inspect metadata/diagnostics for:
   - `ride_segment`
   - `merged_ride_fragments`
   - `RIDE_BOUNDARY_UNCERTAIN`
   - `IDENTITY_UNCERTAIN`
   - `MULTI_PERSON_CLIP`
   - `source_evidence_visual_uploaded`
   - `qa_review_required`
   - `athlete_id`
   - candidate ledger selected/dropped reason
4. Confirm no normal draft mixes athletes, repeats the same athlete as multiple drafts, repeats the same source window, drops valuable social moments silently, or cuts a ride before the natural end.

## Remaining priority order

### P0 — Candidate decision ledger and value feedback capture

Add a run-level ledger and feedback event schema before another deep ranking/QA change. Without a ledger, we cannot tell why a good high-five moment disappeared or why duplicate athlete drafts survived.

### P1 — Run-level athlete canonicalization

Assign stable `athlete_id` values across the run and prevent multiple standalone drafts for the same athlete unless explicitly grouped.

### P2 — Same-clip multi-person detection and wave completion scoring

Add detection/QA fields for `MULTI_PERSON_CLIP` and `wave_completion_score` so the operator can see why a clip is unsafe or incomplete.

### P3 — Operator UI gating and metadata visibility

Disable or demote Approve for QA/review-required drafts and show the exact blocking reason.

### P4 — Multi-video parallel upload UX

Make the upload button support multi-select, parallel upload, shared batch id, per-file progress, and batch-safe rate limiting.

### P5 — Production detector/tracker integration

Convert the perception foundation into a real production pass that emits detections/tracklets for source videos. This remains the biggest architectural gap between desired and actual design.

### P6 — Replace runtime shims with first-class pipeline stages

Consolidate runtime hooks/guards into explicit stages: perception -> candidate ledger -> value ranking -> ride segmentation -> athlete canonicalization -> identity continuity -> editing -> context/source QA -> upload.

## Decision

Do not mark the audit as complete. The next repair should not be another prompt-only QA tweak. The next PR should add a candidate decision ledger plus operator feedback/value labels, because current failures include both false positives and false negatives.

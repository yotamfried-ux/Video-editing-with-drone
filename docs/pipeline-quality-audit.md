# Pipeline quality audit

Date: 2026-07-04

Scope: SportReel / D-to-R pipeline reel quality: deterministic perception, athlete identity, crop/framing, cross-source duplicates, moment selection, editor policy, QA gating, diagnostics, and operational validation.

This file is the working audit log for the pipeline-quality repair loops. Update it whenever a gap is fixed, rejected, superseded, or converted into a dedicated PR/issue. Do not rely on chat history as the source of truth.

## Operating rule

Every repair loop must follow the project rules:

1. Verify the root cause from code, logs, Actions, PR diff, status rows, or real outputs before changing behavior.
2. Make the smallest precise change that proves a new invariant.
3. Add a deterministic contract test or smoke procedure for every fix.
4. Do not claim the reel-quality problem is solved until a real pipeline run and draft output validate it.
5. Use CodeRabbit comments when available. If CodeRabbit is rate-limited or does not review, perform and document self-review.

## Current verified state

### PR #83 — pipeline dispatch status

Status: merged.

Fixed:

- `POST /api/operator/pipeline/start` no longer leaves a newly-created run at `dispatching` after GitHub accepts the repository dispatch.
- The route updates the durable `pipeline_runs` row to `workflow_dispatched` after a 204 dispatch response.
- Dispatch failures move the run to `dispatch_failed` with an actionable error.

Residual risk:

- This improves operator visibility only. It does not change reel-quality decisions inside the Python pipeline.

Primary code paths:

- `web-api/src/app/api/operator/pipeline/start/route.ts`
- `.github/workflows/pipeline-run.yml`
- `scripts/run_tracked.py`

### PR #86 — runtime quality hardening

Status: merged.

Fixed:

- Added `pipeline/runtime_quality.py` and installed it in `scripts/run_tracked.py` before `pipeline.orchestrator` imports analyzer symbols.
- Production runs now drop events below score 6 before editing.
- People with no score >= 6 event are skipped instead of receiving weak filler clips.
- Per-person identity thumbnails are focused around Gemini's `crop_x` / `crop_y` instead of using full-frame drone thumbnails.
- Added `scripts/test_pipeline_quality_contract.py` and wired it into Operator Smoke Check.

Residual risk:

- This is a runtime hardening shim around Gemini output, not a full perception layer.
- It still depends on Gemini-provided `crop_x` / `crop_y`; there is no detector-generated bounding box or stable tracking id yet.
- Real draft quality must still be verified on a new pipeline run.

Primary code paths:

- `pipeline/runtime_quality.py`
- `scripts/run_tracked.py`
- `scripts/test_pipeline_quality_contract.py`
- `.github/workflows/operator-smoke-check.yml`

## Current architecture diagnosis

The pipeline is still mostly LLM-first:

```text
R2/Drive RAW
  -> get_new_videos()
  -> analyze_session() with Gemini video understanding
  -> parsed people/events with descriptions, score, timestamps, crop_x/crop_y
  -> cluster_clips() using descriptions/thumbnails
  -> compile_multi_source_reel()
  -> QA after render
  -> upload draft
```

Target architecture should become perception-first plus LLM editorial reasoning:

```text
R2/Drive RAW
  -> deterministic perception pass: detections, bboxes, tracker ids, confidence, visible ratio
  -> event candidates from tracklets
  -> Gemini reviews focused candidates, not the entire responsibility surface
  -> identity clustering uses track evidence and focused thumbnails
  -> editor uses bbox-derived crop and quality metadata
  -> QA verifies hard invariants before draft upload
```

Roboflow `supervision` should be used as the local computer-vision plumbing layer for detections, bbox math, video utilities, annotations, filtering, and tracker-compatible schemas. It should not replace Gemini. Gemini remains useful for editorial/sports-context decisions after deterministic perception narrows and validates the candidate moments.

Important constraint:

- Do not build new code directly on deprecated `sv.ByteTrack`. If tracking is added, use a supported tracker adapter or isolate the tracker behind our own interface so we can replace it without touching the pipeline.

## Open quality gaps

### PQ-001 — No deterministic perception layer

Severity: critical.

Area: `pipeline/`, `requirements.txt`, Operator Smoke Check.

Problem:

- The pipeline relies on Gemini JSON for person identity, event timestamps, score, and crop hints.
- There is no independent object/person/surfer detection layer producing bounding boxes, confidence, visible ratio, or tracker ids.

Root cause:

- The system is LLM-first rather than CV-first. Gemini has too much responsibility: identify people, choose moments, score quality, estimate crop, and recommend edit hints.

Target invariant:

- Before editing, every candidate event should have perception metadata when perception is enabled:
  - `xyxy` bounding box or explicit `no_detection` reason.
  - `confidence`.
  - `track_id` when tracking is available.
  - `visible_ratio` / presence across the event window.
  - frame/time references used to compute the crop.

Repair loop:

1. Add `supervision` as a dependency behind a dedicated perception module.
2. Add `pipeline/perception/schema.py` for normalized detections/tracklets.
3. Add `pipeline/perception/supervision_adapter.py` for conversion to/from `sv.Detections`.
4. Add `pipeline/perception/crop_math.py` for bbox -> crop_x/crop_y calculations.
5. Add `scripts/test_perception_contract.py` with synthetic detections.
6. Wire the test into `.github/workflows/operator-smoke-check.yml`.
7. Keep production behavior unchanged until the contract passes.

Suggested first PR:

- Branch: `feat/perception-foundation`
- Title: `Add Supervision perception foundation`
- Files:
  - `requirements.txt`
  - `.github/workflows/operator-smoke-check.yml`
  - `pipeline/perception/__init__.py`
  - `pipeline/perception/schema.py`
  - `pipeline/perception/supervision_adapter.py`
  - `pipeline/perception/crop_math.py`
  - `scripts/test_perception_contract.py`

Verification required:

- `python scripts/test_perception_contract.py` passes.
- Operator Smoke Check runs the new perception contract.
- No production pipeline behavior changes in the foundation PR.

Status update, 2026-07-16:

- The perception foundation described above is built and merged:
  `pipeline/perception/schema.py`, `supervision_adapter.py`, `crop_math.py`,
  `producer.py` (real Ultralytics YOLO + BoT-SORT backend), and
  `scripts/test_perception_contract.py` all exist and are wired into
  Operator Smoke Check.
- Whether perception should be required by default (vs. opt-in, silently
  skipped) was an open, undecided default. This is now resolved: see
  `docs/audit/perception-default-activation-decision-20260716.md`. Decision:
  stay opt-in until real-run track-fragmentation and per-video cost/runtime
  evidence justify flipping `SPORTREEL_REQUIRE_PERCEPTION` on by default.
  That doc records the concrete revisit condition.

### PQ-002 — Athlete identity can merge two people or split one person

Severity: critical.

Area: `pipeline/stages/identity.py`, `pipeline/runtime_quality.py`.

Problem:

- Identity clustering uses descriptions and thumbnails, not stable per-frame tracking evidence.
- Medium-confidence multi-clip clusters can remain merged.
- If visual verification fails technically, the current behavior can keep the cluster as-is.

Root cause:

- Identity is inferred from weak evidence: text labels and one thumbnail per person/event.
- There is no tracker id or bbox trajectory to verify that an event belongs to the same athlete.

Target invariant:

- The pipeline must never knowingly create a normal draft reel that mixes two detected athletes.
- Same-source different tracker ids must stay separated unless a verified handoff/merge rule proves they are the same athlete.
- Verification errors for multi-athlete clusters should be fail-safe, not fail-open.

Repair loop:

1. Add perception metadata to clip analyses without changing editor output yet.
2. Update identity clustering to consume `track_id`, bbox summaries, and focused thumbnails.
3. Split clusters when medium confidence lacks perception evidence.
4. Change visual-verifier exception behavior for multi-appearance clusters from keep-as-is to split or manual-review flag.
5. Add `scripts/test_identity_perception_contract.py`.

Primary code references:

- `pipeline/stages/identity.py`
- `pipeline/runtime_quality.py`
- `pipeline/stages/analyzer.py`

Verification required:

- Synthetic two-athlete same-clip fixture produces two clusters.
- Visual verifier exception on a multi-appearance cluster does not keep a risky merge as a normal cluster.
- Existing same-clip conflict and number-conflict safeguards still pass.

### PQ-003 — Crop/framing is based on Gemini crop hints instead of bboxes

Severity: critical.

Area: `pipeline/stages/analyzer.py`, `pipeline/stages/editor.py`, `pipeline/runtime_quality.py`.

Problem:

- `crop_x` and `crop_y` are parsed from Gemini output and clamped, but not verified against a real detection.
- `QA_CROP_CHECK` is disabled by default, so a bad crop can pass into the final reel.

Root cause:

- The editor lacks a measured athlete position. It crops based on an LLM hint instead of a bbox/track center.

Target invariant:

- When perception is enabled, crop should be computed from bbox/track center.
- If no detection exists for the candidate moment, the event should be flagged or dropped according to policy.
- `QA_CROP_CHECK` should become a secondary check, not the first proof of framing.

Repair loop:

1. Implement bbox -> crop center in `pipeline/perception/crop_math.py`.
2. Add event-level fields: `bbox_xyxy`, `perception_confidence`, `track_id`, `visible_ratio`.
3. Update editor/runtimes to prefer bbox-derived crop over Gemini crop.
4. Add a fallback warning when only Gemini crop is available.
5. Add `scripts/test_crop_from_bbox_contract.py`.

Primary code references:

- `pipeline/stages/analyzer.py`
- `pipeline/stages/editor.py`
- `pipeline/runtime_quality.py`
- `config/settings.py`

Verification required:

- Left/right/center bbox fixtures produce expected crop centers.
- Out-of-bounds bboxes clamp safely.
- Low visible ratio does not produce a normal unflagged event.

### PQ-004 — Raw queue has no batch/session isolation

Severity: high.

Area: R2 upload, operator API, pipeline workflow, storage adapter.

Problem:

- R2 upload keys currently go under `raw/<timestamp>_<filename>`.
- The pipeline lists all videos in `raw/`.
- The system cannot reliably distinguish one athlete/session/batch from another.

Root cause:

- Upload and pipeline dispatch are not scoped to a durable `batch_id` or session prefix.

Target invariant:

- A manual pipeline run should process only the intended batch unless explicitly configured to process the full raw queue.

Repair loop:

1. Add `upload_batch_id` or use the created `pipeline_run_id` as a batch prefix.
2. Change R2 upload key from `raw/<filename>` to `raw/<batch_id>/<filename>`.
3. Pass `batch_id` in `repository_dispatch.client_payload`.
4. Teach `integrations/r2_storage.get_new_videos()` to accept or read a batch prefix.
5. Preserve reset/rerun semantics without deleting unrelated batches.
6. Add contract tests for scoped listing and reset.

Primary code references:

- `web-api/src/app/api/operator/upload/route.ts`
- `web-api/src/lib/r2-storage.ts`
- `web-api/src/app/api/operator/pipeline/start/route.ts`
- `integrations/r2_storage.py`
- `.github/workflows/pipeline-run.yml`
- `scripts/run_tracked.py`

Verification required:

- Batch A upload does not appear in Batch B processing.
- Pipeline dispatch includes the correct batch id.
- Reset/rerun does not destroy unrelated raw batches.

### PQ-005 — Cross-source duplicate moments are not detected

Severity: high.

Area: `pipeline/stages/editor.py`, identity/perception metadata.

Problem:

- `_sanitize_events()` deduplicates overlapping timestamps within one source video.
- It cannot prove that the same physical wave/action was uploaded in two different files.

Root cause:

- There is no event fingerprint across sources: no cropped thumbnail hash, no track trajectory summary, no visual similarity score, and no wave/action fingerprint.

Target invariant:

- The same physical moment should not appear twice in a normal draft reel, even if it came from two source files.

Repair loop:

1. Add `pipeline/perception/event_fingerprint.py`.
2. Build fingerprints from cropped thumbnail, bbox trajectory, source timestamp window, event type, and optional embedding.
3. Run cross-source dedup before `_partition_events()`.
4. Keep the highest-quality duplicate according to score + visibility + action evidence.
5. Add `scripts/test_cross_source_dedup_contract.py`.

Primary code references:

- `pipeline/stages/editor.py`
- `pipeline/stages/identity.py`
- `pipeline/perception/*`

Verification required:

- Two events from different sources with the same fingerprint produce one kept event.
- Two distinct waves from the same athlete remain separate.
- Lower-quality duplicate never replaces a higher-quality event.

### PQ-006 — Weak moments can still originate in analyzer output

Severity: high.

Area: `pipeline/stages/analyzer.py`, `pipeline/runtime_quality.py`.

Problem:

- PR #86 drops score < 6 at runtime, but the original analyzer parser still contains a fallback that can select score 5 moments when no score >= 6 exists.

Root cause:

- The parser prioritizes giving every participant a personal clip over strict quality.

Target invariant:

- A normal draft should never include a weak filler event simply because no strong event exists.
- If an athlete has no qualifying moment, they should be skipped or flagged for manual review.

Repair loop:

1. Move the PR #86 runtime policy directly into `pipeline/stages/analyzer.py`.
2. Remove the score-5 fallback from the parser.
3. Keep `runtime_quality.py` only as a short-term guard or remove it once analyzer owns the behavior.
4. Add/update tests proving score 5 only output becomes no event.
5. Run a real pipeline on a weak-session fixture and confirm no weak draft is created.

Primary code references:

- `pipeline/stages/analyzer.py`
- `pipeline/runtime_quality.py`
- `scripts/test_pipeline_quality_contract.py`

Verification required:

- Synthetic analyzer JSON with only score 5 events returns zero persons/events.
- Score >= 6 events still pass.
- Runtime and analyzer policies do not diverge.

### PQ-007 — Event timestamps and cut policy can produce short or awkward clips

Severity: medium-high.

Area: `pipeline/stages/analyzer.py`, `pipeline/stages/editor.py`, QA gate.

Problem:

- Event `start` and `end` come from Gemini.
- The editor clamps or trims events; non-climax clips over the cap are trimmed from the front.
- Premature-cut correction is only post-render QA and depends on the QA model catching it.

Root cause:

- There is no deterministic peak/action window from track motion or sport-specific action cues.

Target invariant:

- Event windows should include visible setup -> peak -> outcome, or be dropped/flagged.
- Non-climax caps should not remove critical context.

Repair loop:

1. Add event-window diagnostics: original Gemini window, clamped window, final cut window, reason for any adjustment.
2. Use perception track continuity to validate event duration.
3. Add a peak-time field when available.
4. Change cap behavior to respect peak/outcome windows.
5. Add `scripts/test_event_window_contract.py`.

Primary code references:

- `pipeline/stages/analyzer.py`
- `pipeline/stages/editor.py`
- `pipeline/orchestrator.py`

Verification required:

- Premature-cut fixture extends or rejects the event deterministically.
- Dead-time-only window is dropped.
- Editor metadata explains every time adjustment.

### PQ-008 — Editor chooses opener/climax from Gemini score alone

Severity: high.

Area: `pipeline/stages/editor.py`.

Problem:

- `_partition_events()` sorts by score.
- `_narrative_order()` uses second-best as opener and best as climax.
- The teaser is derived from the climax.
- If score is wrong, the entire reel structure can be wrong.

Root cause:

- Editor has no independent action-strength, visibility, or mixed-athlete evidence.

Target invariant:

- Climax and teaser must require both editorial score and perception quality.
- A high Gemini score with poor visibility or mixed-athlete evidence cannot become climax.

Repair loop:

1. Add an event quality composite: score, visible ratio, track continuity, motion/action evidence, identity confidence.
2. Use composite quality for climax/opener selection.
3. Disable teaser if no qualified climax exists.
4. Add `scripts/test_editor_narrative_contract.py`.

Primary code references:

- `pipeline/stages/editor.py`
- `pipeline/orchestrator.py`

Verification required:

- Highest-score low-visibility event cannot be climax.
- No qualified climax means no teaser.
- Teaser is never generated from a weak or uncertain event.

### PQ-009 — QA is late and can upload flagged outputs instead of preventing normal bad drafts

Severity: high.

Area: `pipeline/orchestrator.py`, QA metadata, draft upload.

Problem:

- QA runs after rendering.
- Re-edit can remove/adjust clips, but if QA still fails after retries, the reel can be uploaded as flagged.
- The operator still needs to interpret what failed.

Root cause:

- QA is a post-render safety net, not a first-class gate with full event/perception diagnostics.

Target invariant:

- Critical defects should not produce normal drafts.
- Every flagged draft must include structured metadata explaining exactly what failed.

Repair loop:

1. Add `pipeline/diagnostics.py` to capture analysis, perception, identity, editor, and QA decisions.
2. Store metadata next to review drafts or under `metadata/` in R2.
3. Change blocking defect policy for `IDENTITY_MISMATCH`, `NO_VISIBLE_ACTION`, `BAD_FRAMING`, `DUPLICATE_MOMENT`.
4. Add `scripts/test_qa_gate_contract.py`.

Primary code references:

- `pipeline/orchestrator.py`
- `pipeline/stages/analyzer.py`
- `pipeline/stages/editor.py`
- `integrations/r2_storage.py`

Verification required:

- Critical identity mismatch is not uploaded as a normal draft.
- Flagged output includes metadata with defect type, event id, source, and decision.
- QA retry count and final verdict are persisted.

### PQ-010 — Reel-quality debugging is not fully reconstructable from artifacts

Severity: medium-high.

Area: pipeline logs, artifacts, R2 metadata, operator review UI.

Problem:

- To understand a bad draft today, we need to inspect logs and infer which Gemini event/cluster/editor choice produced it.
- The final output is not always traceable back to raw Gemini JSON, identity clusters, ordered events, and QA decisions.

Root cause:

- Diagnostics were added incrementally, not as a unified audit trail.

Target invariant:

- For each draft reel, the repo should produce a machine-readable audit artifact:
  - source videos
  - raw Gemini events
  - perception tracks
  - identity clusters
  - ordered events
  - dropped events and reasons
  - QA defects and fixes
  - final upload key

Repair loop:

1. Define `reels_metadata.json` schema for full traceability.
2. Persist it in R2/Drive metadata beside the draft.
3. Add a lightweight operator API route to retrieve metadata for a review draft.
4. Add contract tests proving required metadata fields exist.

Primary code references:

- `config/settings.py`
- `pipeline/orchestrator.py`
- `pipeline/stages/editor.py`
- `integrations/r2_storage.py`

Verification required:

- Each review draft has matching metadata.
- Metadata can answer: why this clip, why this crop, why this order, why this QA verdict.

## Recommended repair order

1. PQ-001 — Add Supervision perception foundation with no production behavior change.
2. PQ-003 — Use bbox-derived crop/framing when perception data exists.
3. PQ-002 — Make identity clustering fail-safe using perception evidence.
4. PQ-004 — Add batch/session isolation so runs process intended footage only.
5. PQ-005 — Add cross-source duplicate detection.
6. PQ-006 — Move weak-moment filtering into analyzer and remove score-5 fallback.
7. PQ-007 — Add event-window validation and cut diagnostics.
8. PQ-008 — Change editor climax/teaser policy to use composite quality.
9. PQ-009 — Harden QA gate and flagged-output behavior.
10. PQ-010 — Add full per-draft diagnostic artifact.

## Real validation matrix

A future pipeline-quality fix is not complete until it passes these layers:

| Layer | Required validation |
|---|---|
| Static contract | Targeted `scripts/test_*.py` contract passes. |
| CI | Operator Smoke Check runs the relevant contract. |
| Runtime path | Change is installed before `pipeline.orchestrator` imports stage functions when needed. |
| Real pipeline run | GitHub Actions run succeeds or fails with actionable diagnostic. |
| Draft review | Generated draft is inspected in the operator app. |
| Metadata | The draft can be traced to source events, identity decision, edit order, and QA verdict. |

## First implementation target

Next PR should be docs/infra-light only:

```text
Add Supervision perception foundation
```

Expected changes:

- `requirements.txt`: add pinned `supervision` dependency.
- `pipeline/perception/`: add schema, supervision adapter, crop math.
- `scripts/test_perception_contract.py`: prove synthetic bbox/confidence/tracker schema and crop conversion.
- `.github/workflows/operator-smoke-check.yml`: run perception contract when perception files or requirements change.

Do not connect this foundation to production editing until the foundation contract is green and a debug runner has proven useful on a real surf/drone video.

# Wave continuity audit — real run follow-up

Status: addendum to `docs/pipeline-quality-audit.md`, `docs/pipeline-quality-audit-real-run-20260705.md`, and `docs/pipeline-context-qa-audit-20260705.md`.

## Real-output finding

Operator review still shows two product-level failures:

1. A good surf ride can stop before the natural finish.
2. One surf ride can be split into two clips or fragments.
3. Similar surfers can leak into each other's drafts when clothing or board evidence is different but visual appearance is close.

The editorial goal for surf is clear: show a good wave from the beginning of the ride through the natural finish/exit/fall. The system should not treat a wave as arbitrary highlight snippets.

## Official references

- AWS Rekognition Video Segment Detection: segment detection returns SMPTE timecodes, timestamps, and frame numbers. Shot detection returns start, end, duration, and shot count. AWS defines a shot as continuous action in time and space.
- Adobe Premiere Scene Edit Detection: professional edit systems operate on detected edit points and timeline cut boundaries.
- Google Cloud Video Intelligence: video analysis is organized around video, shot, and frame-level metadata, so editing decisions should be backed by temporal/frame evidence.
- Gemini Video Understanding: video QA can inspect video and timestamps, but fast actions can be missed, so deterministic source-window checks are still needed.

## REAL-WAVE-001 — Surf ride is not an atomic editorial unit

Severity: critical.

Problem:

- Current pipeline treats `event.start` and `event.end` as highlight fragments.
- `cut_window_guard` adds tail padding when outcome evidence is missing, but padding is not the same as modeling the whole ride.
- `window_policy` preserves `outcome_end` only when that metadata exists.
- QA reacts after the cut exists; it does not require that the selected unit is a complete ride.

Target invariant:

```text
A normal surf draft must be built from complete ride segments: ride_start/takeoff -> peak/action -> ride_end/outcome. A fragment without complete ride evidence is QA-FLAGGED/manual review, not normal approval.
```

Required behavior:

1. Introduce a surf `ride_segment` schema with `ride_start`, `takeoff_time`, `peak_time`, `ride_end`, `outcome_type`, `source`, `track_id`, and evidence/confidence fields.
2. Normalize analyzer/Gemini events into ride segments before editing.
3. Merge adjacent same-surfer events from the same source into one ride when their source windows overlap or have only a short gap.
4. For normal review, cut from ride start to ride end, with small pre/post padding only after full ride boundaries are known.
5. Do not split one ride into multiple normal clips unless it is explicitly a teaser plus full payoff, and diagnostics must mark this relationship.
6. If ride end is unknown, infer it from source-window visual evidence or flag `RIDE_BOUNDARY_UNCERTAIN` / `QA_REVIEW_REQUIRED`.
7. Add contracts proving: no mid-ride cut, no two-part split of one ride, adjacent fragments merge, and incomplete ride boundary is fail-closed.

## REAL-ID-003 — Similar-surfer leakage inside source windows

Severity: critical.

Problem:

- Two visually similar women with similar boards can leak into each other's drafts even when clothing differs.
- Current identity gating is strongest across appearances/clusters, but weaker inside one source window or one ride.

Target invariant:

```text
A normal surf draft must preserve one athlete track across the entire ride segment. If the source window may contain multiple similar athletes and stable track/bbox evidence is missing, the draft is manual review.
```

Required behavior:

1. Add same-source identity continuity validation inside each ride segment.
2. Require stable `track_id` or bbox/thumbnail continuity through the ride for normal approval.
3. If stable identity evidence is missing and multiple visible athlete candidates appear, attach `IDENTITY_UNCERTAIN` or `IDENTITY_MISMATCH` and flag review.
4. Add contracts for two similar athletes with different clothing/boards in the same source window.

## Diagnosis summary

The latest fixes improved QA visibility and source evidence, but they are still downstream of the editorial unit selection. The root issue is earlier: the pipeline does not yet define a wave/ride as the atomic editing unit. It selects and orders event fragments, then tries to repair cuts using padding and QA. That can still produce mid-wave cuts and duplicated/split rides.

## Plan — next repair PR

Single PR objective: `Add surf ride continuity gate`.

Planned steps:

1. Add `pipeline/surf_ride_segment.py`.
2. Implement `merge_ride_fragments(events)` to combine same-source/same-track overlapping or near-adjacent fragments into one ride.
3. Implement `validate_ride_segment(segment)` with required fields: `ride_start`, `peak_time`, `ride_end`, source, identity evidence.
4. Hook before `compile_multi_source_reel` / `create_reel` so the editor receives ride segments, not raw highlight fragments.
5. Update `window_policy` / `cut_window_guard` to prefer ride boundaries over raw event start/end or generic tail padding.
6. Add QA diagnostics: `RIDE_BOUNDARY_UNCERTAIN`, `MID_RIDE_CUT`, `RIDE_SPLIT`, `IDENTITY_UNCERTAIN`.
7. Add tests:
   - full ride passes from start to end;
   - two adjacent fragments of the same wave merge;
   - mid-wave fragment is not normal review;
   - same wave cannot become two normal clips;
   - similar surfers without stable track evidence are flagged.
8. Run focused CI and then a real pipeline validation.

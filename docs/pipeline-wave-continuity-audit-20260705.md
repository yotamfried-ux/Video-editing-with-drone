# Wave continuity audit — real run follow-up

Status: addendum to `docs/pipeline-quality-audit.md`, `docs/pipeline-quality-audit-real-run-20260705.md`, and `docs/pipeline-context-qa-audit-20260705.md`.

## Real-output finding

Operator review still shows these product-level failures:

1. A good surf ride can stop before the natural finish.
2. One surf ride can be split into two clips or fragments.
3. Similar surfers can leak into each other's drafts when clothing or board evidence is different but visual appearance is close.

The editorial goal for surf is to show a good wave from the beginning of the ride through the natural finish/exit/fall. The system should not treat a wave as arbitrary highlight snippets.

## Official references

- AWS Rekognition Video Segment Detection: segment detection returns SMPTE timecodes, timestamps, and frame numbers; shot detection returns start, end, duration, and shot count. AWS defines a shot as continuous action in time and space.
- Adobe Premiere Scene Edit Detection: professional edit systems operate on detected edit points and timeline cut boundaries.
- Google Cloud Video Intelligence: video analysis is organized around video, shot, and frame-level metadata, so editing decisions should be backed by temporal/frame evidence.
- Gemini Video Understanding: video QA can inspect video and timestamps, but fast actions can be missed, so deterministic source-window checks are still needed.

## REAL-WAVE-001 — Surf ride is not an atomic editorial unit

Severity: critical.

Target invariant:

```text
A normal surf draft must be built from complete ride segments: ride_start/takeoff -> peak/action -> ride_end/outcome. A fragment without complete ride evidence is QA-FLAGGED/manual review, not normal approval.
```

Required behavior:

1. Normalize surf fragments into `ride_segment` objects before editing.
2. Merge adjacent same-source/same-track fragments into one ride.
3. Cut normal review drafts from ride start to ride end.
4. Do not split one ride into two normal clips unless explicitly marked as teaser plus full payoff.
5. If ride end is unknown, flag `RIDE_BOUNDARY_UNCERTAIN` / `QA_REVIEW_REQUIRED`.

## REAL-ID-003 — Similar-surfer leakage inside source windows

Severity: critical.

Target invariant:

```text
A normal surf draft must preserve one athlete track across the entire ride segment. If stable track/bbox evidence is missing, the draft is manual review.
```

Required behavior:

1. Validate identity continuity inside each ride segment.
2. Require stable `track_id` or equivalent evidence for normal approval.
3. If evidence is missing, attach `IDENTITY_UNCERTAIN` or `IDENTITY_MISMATCH` and flag review.

## Repair implemented in PR

1. Add `pipeline/surf_ride_segment.py`.
2. Add runtime `pipeline/surf_ride_gate.py` before editor partitioning.
3. Merge adjacent ride fragments and preserve diagnostics.
4. Surface `RIDE_BOUNDARY_UNCERTAIN` and `IDENTITY_UNCERTAIN` into QA evidence.
5. Add contracts for merge behavior, uncertainty flags, and QA blocking context.

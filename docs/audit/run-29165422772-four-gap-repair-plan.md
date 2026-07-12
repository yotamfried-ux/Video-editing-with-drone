# Run 29165422772 — Four-Gap Repair Plan

## Scope

- Repository: `yotamfried-ux/Video-editing-with-drone`
- Production workflow run: `29165422772`
- Source commit: `a0774ecc81f5dcea72aa974094dd5d3143a1185e`
- Repair branch: `fix-chunk-identity-timeline-reedit-contract`

The run proved that primary-actor continuity increased recall, but it also exposed four connected data and editing-contract failures. This plan fixes them as one unit because identity, source time, draft lineage, coverage telemetry, and QA repair all rely on the same event record.

## Gap 1 — Chunk-local person IDs were treated as global identity

### Evidence

Gemini reused labels such as `person_A`, `person_B`, and `person_C` independently in each uploaded chunk. Different descriptions and equipment were therefore associated with the same raw label. This created mixed identity evidence and unreliable coverage groups.

### Correction

`pipeline/chunk_timeline_runtime.py`:

- namespaces every local model label as `chunk_NN:person_X`;
- retains the original label in `source_person_id`;
- retains `chunk_index`, chunk bounds, and source filename;
- does not merge people by description during chunk assembly;
- leaves later canonical identity merging to evidence-based identity layers.

### Acceptance

- `chunk_00:person_A` and `chunk_01:person_A` remain distinct inputs.
- No two chunks can collide solely because Gemini reused a local label.
- Different athletes are not merged by description-prefix heuristics.

## Gap 2 — Athlete/source lineage disappeared before the draft trace

### Evidence

The prior `draft_decision_trace.json` contained selected windows but lost `person_id`, `athlete_id`, and source linkage. `athlete_coverage_report.json` therefore grouped selected actions under `unknown_cluster` and could not represent the produced drafts accurately.

### Correction

`pipeline/draft_identity_metadata.py` and the trace/ledger builders now preserve:

- `person_id`, `source_person_id`, `chunk_person_id`;
- `athlete_id` and canonical evidence fields;
- source video and source path;
- chunk-local and source-global timing evidence;
- final-cut and QA re-edit evidence.

The candidate ledger merges final draft lineage back into the selector candidate representing the same physical source window. Athlete coverage uses the namespaced person key shared by selected and rejected candidates and reports selected-lineage completeness.

### Acceptance

For every selected final action:

```text
person_id != null
athlete_id != null
source_video != null
```

Required metrics:

```text
selected_identity_lineage_complete_count
selected_identity_lineage_completeness_rate
```

A complete production run must reach a completeness rate of `1.0` before its athlete coverage can be treated as authoritative.

## Gap 3 — Chunk timestamps could be shifted twice or escape source bounds

### Evidence

The source duration was approximately 548.9 seconds, while selector/analyzer events appeared at `643–716` and `738–755`. The old merge always added `chunk_index × 480`, even when Gemini had already returned source-global timestamps.

### Correction

One shared deterministic contract now handles both parsed analyzer events and raw selector telemetry:

1. calculate actual chunk bounds from source duration;
2. identify whether each returned window is chunk-local or source-global;
3. shift local windows exactly once;
4. retain global windows without a second shift;
5. clamp small boundary overruns to the real chunk;
6. discard windows outside the chunk or with less than four usable seconds;
7. record the original values, basis, clamp, and explicit discard reason.

### Acceptance

- No retained event end exceeds source duration.
- Analyzer and selector artifacts report the same normalized physical window.
- Invalid selected candidates become explicit discards rather than disappearing in editor sanitization.
- Diagnostics expose invalid and clamped timestamp counts.

## Gap 4 — PREMATURE_CUT repair was re-capped by the editor

### Evidence

The QA loop extended source events by three seconds, for example `332–400 → 332–403 → 332–406`, while the final renderer continued producing a 15-second source cut. The repair changed metadata but not the actual video window.

### Correction

`pipeline/qa_reedit_window_contract.py`:

- detects source-tail extensions created for `PREMATURE_CUT` or `CUT_TOO_EARLY`;
- marks the repair as an explicit long-cut override;
- permits a final source window greater than the normal 15-second single-clip cap;
- applies a strict 30-second maximum;
- preserves the action tail when the source event is longer than the maximum;
- makes editor, window policy, sidecar gate, metadata, and trace use the same final-cut bounds.

Example:

```text
requested source event: 332–403
normal cap: 15 seconds
QA repair safety cap: 30 seconds
actual repaired final cut: 373–403
```

### Acceptance

- A valid 18-second repair renders all 18 seconds.
- A longer repair renders at most 30 seconds and includes the requested ending.
- Non-PREMATURE_CUT defects never receive the override.
- The actual final-cut window is persisted in draft diagnostics.

## Regression contracts

- `scripts/test_chunk_identity_timeline_contract.py`
- `scripts/test_draft_identity_lineage_contract.py`
- `scripts/test_qa_reedit_window_contract.py`

They are required by Operator Smoke Check together with all existing identity, QA, deduplication, selection, coverage, and source-evidence contracts.

## Merge gate

The PR may be merged only when:

- all repository workflows pass on the final head;
- all three new contracts pass;
- existing QA, identity, primary-actor, deduplication, and coverage contracts remain green;
- no unresolved review thread remains;
- `main` is verified identical to the merge commit.

## Post-merge production validation

Static and contract tests can prove the data flow and render-window behavior, but they cannot prove the real footage result. A new pipeline run on the merge commit must verify:

- no cross-chunk person-label collision;
- no selected timestamp outside source bounds;
- `selected_identity_lineage_completeness_rate = 1.0`;
- repaired PREMATURE_CUT final-cut duration exceeds 15 seconds when needed and remains at or below 30 seconds;
- no identity mismatch or QA gate bypass regression.

# Context-aware QA audit — real run follow-up

Status: addendum to `docs/pipeline-quality-audit.md` and `docs/pipeline-quality-audit-real-run-20260705.md`.

## Real-output finding

A later operator review showed that multiple drafts from the same run represented the same surfer / same rendered content under different descriptions. This is a run-level defect, not just a within-reel duplicate.

## REAL-QA-001 — QA sees final reel only, not source/edit context

Severity: critical.

Problem:

- `qa_check_reel()` evaluates a compiled reel with only `sport` and `athlete_label` context.
- It does not receive the diagnostic artifact / edit JSON.
- It does not receive original source windows.
- It does not compare all drafts in the same run.

Target invariant:

```text
QA must judge the final draft against the edit decisions and source windows that produced it.
```

Required behavior:

1. Build a QA package per draft containing draft path/name, events, source windows, edit timing, identity evidence, duplicate evidence, and diagnostic artifact fields.
2. Before upload, run a deterministic run-level QA gate over all draft packages.
3. Detect duplicate rendered drafts even when descriptions differ.
4. Mark or remove duplicates before normal review upload.
5. Preserve blocked duplicate evidence in metadata on the kept draft.
6. Future enhancement: use the package to ask a source-aware LLM/video QA judge to compare final draft segments against original source windows.

## REAL-DUP-002 — Duplicate rendered drafts emitted under different descriptions

Severity: critical.

Problem:

- Two or more normal review drafts can represent the same source/time/event sequence but use different Gemini-generated athlete descriptions.
- The previous final duplicate guard removes duplicates within an event list, but does not compare all rendered drafts before upload.

Target invariant:

```text
The same source/time/event sequence must not be uploaded as multiple normal review drafts in the same run.
```

Repair loop:

1. Add a context QA module that fingerprints draft packages from source windows, event ids, fingerprints, and timing.
2. Before upload, compare all pending drafts in `_compile_clusters`.
3. Keep the best draft and drop duplicates from `pending` / `pending_meta` before upload.
4. Attach `DUPLICATE_DRAFT` evidence to the kept draft's events so `diagnostic_artifact.dropped_events` explains what was removed.
5. Add a focused contract proving same source/time windows under different draft names produce one upload candidate only.

## REAL-UPLOAD-003 — Long-video delayed uploads can reference overwritten render paths

Severity: high.

Evidence:

- Real pipeline run `28938769332` succeeded and uploaded one final REVIEW draft, but `run_tracked.log` contained repeated `Draft upload failed` / `FileNotFoundError` messages for earlier long-video QA candidates.
- The missing path was the deterministic editor output, for example `/tmp/dtor/REEL_2026-07-04T18-34-54_1000270686_surfing.mp4`.

Problem:

- `context_qa_long_video.py` delays upload until all person drafts have passed context QA and duplicate filtering.
- Long-video persons and QA re-edit attempts can reuse the same deterministic `REEL_<source>_<sport>.mp4` path.
- Later renders can overwrite or remove earlier accepted candidates before the delayed upload loop reaches them.
- The final run can still pass when one later draft uploads successfully, but the failed stale uploads pollute diagnostics and can hide a real loss of intended REVIEW drafts.

Target invariant:

```text
Every long-video draft candidate kept for delayed upload must point at a stable rendered file that cannot be overwritten by later person/QA renders.
```

Repair loop:

1. Snapshot each long-video candidate to a unique `draft-candidate` staging file immediately after the candidate name/events are decided.
2. Run duplicate filtering over the staged candidates.
3. Remove staged files for dropped duplicates.
4. Upload only staged files, then remove the staged file after upload attempt.
5. Add a contract test proving two renders from the same deterministic reel path preserve different bytes in different staged files.

## REAL-QA-002 — QA must fail closed

Severity: high.

Problem:

- Existing reel QA returns a synthetic PASS when the QA call fails technically.
- That is acceptable for avoiding outages, but not acceptable for normal approval when the output is uncertain.

Target invariant:

```text
QA uncertainty must become manual review / flagged, not normal approval.
```

Follow-up after REAL-DUP-002:

- Add a fail-closed QA wrapper that converts QA exceptions / skipped QA into `QA_UNCERTAIN` diagnostics for normal review drafts.

## Official references to consult

- OpenAI Evals: evaluators require explicit criteria, test data, and graders instead of broad subjective prompts.
- OpenAI Graders: combine model-based graders with deterministic code/string/similarity graders.
- LangSmith evaluation: online evaluators should inspect production traces, inputs, outputs, intermediate steps, and metadata.
- Gemini Video Understanding: video QA can use file inputs and timestamps, but fast action can be missed, so deterministic source-window checks are still required.

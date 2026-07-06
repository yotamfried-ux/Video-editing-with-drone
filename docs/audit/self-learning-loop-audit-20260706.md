# Self-learning loop audit checklist — 2026-07-06

Repo: `yotamfried-ux/Video-editing-with-drone`  
Product: SportReel / D-to-R pipeline

Goal: create a closed improvement loop, not uncontrolled self-modifying code.

Loop: `real run -> evidence capture -> human labels -> baseline metrics -> replay/eval -> fix -> CI -> real-run validation`.

Official references to preserve in implementation:
- Google Cloud MLOps: automation, testing, metadata, monitoring, and continuous operation for ML systems: `https://cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning`
- OpenAI Evals: define expected behavior, run cases, compare outputs, improve safely: `https://platform.openai.com/docs/guides/evals`
- AWS SageMaker Model Monitor: capture production inputs/outputs, create baseline, monitor quality, report violations: `https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html`
- Azure ML monitoring: production inference data, reference data, signals, thresholds, alerts: `https://learn.microsoft.com/en-us/azure/machine-learning/concept-model-monitoring`
- OpenTelemetry signals: collect logs, metrics, traces, and events, not only final artifacts: `https://opentelemetry.io/docs/concepts/signals/`

## Current real-run evidence

- [x] Pipeline produced real drafts.
- [x] General quality improved compared with earlier runs.
- [ ] Same surfer/surfer still appears in more than one draft.
- [ ] Draft labeled for one surfer can include another surfer in the middle.
- [ ] There is still no complete metric-based comparison against the original video.
- [ ] We cannot yet prove which good moments were selected, dropped, or missed.

Status terms:
- `Closed by contract`: code + CI prove the invariant, not necessarily real footage.
- `Pending real-run validation`: code exists, but a real run must prove it.
- `Closed by real run`: real run + artifacts + operator review prove it.
- `Hard gate`: block normal approval.
- `Review-required`: draft exists but cannot be treated as normal.
- `Ranker`: chooses quality/value; must not override safety gates.

---

## Phase 1 — Capture every decision as data

- [ ] Add/verify `candidate_decision_ledger` for every run.
  - Must record: run id, batch id, source video, candidate id, event id/type, start/end, source window, score, selected/dropped, dropped reason.
  - Done when every selected draft and dropped candidate traces to a source window.
- [ ] Store perception evidence per candidate/draft.
  - Must record: primary `track_id`, `visible_track_ids`, `source_window_track_ids`, bbox, confidence, class, sidecar path, model, tracker, `vid_stride`, `imgsz`.
  - Done when a mixed-person draft can be explained from stored evidence alone.
- [ ] Store edit/window evidence per draft.
  - Must record: selected start/end, source window, wave start/peak/end evidence, crop source, crop coordinates, source evidence clip status.
- [ ] Store QA/policy evidence per draft.
  - Must record: `qa_review_required`, blocking reasons, warnings, multi-person flags, duplicate-athlete flags, cut-too-early flags, approval policy.
- [ ] Store run config.
  - Must record: commit SHA, Gemini model, perception command, Ultralytics model/tracker, stride/imgsz, dependency versions, storage backend.

## Phase 2 — Turn human review into labels

- [ ] Create structured draft feedback schema.
  - Fields: draft id, run id, source video, approve/reject/re-edit, problem types, severity, human note, timestamp.
- [ ] Required problem types:
  - [ ] `mixed_subject`
  - [ ] `duplicate_athlete`
  - [ ] `duplicate_moment`
  - [ ] `cut_too_early`
  - [ ] `missed_good_moment`
  - [ ] `boring_clip`
  - [ ] `wrong_person`
  - [ ] `bad_crop`
  - [ ] `bad_title`
  - [ ] `missing_source_evidence`
- [ ] Label the two confirmed failures from the latest real run.
  - [ ] Same surfer duplicated across drafts.
  - [ ] Different surfer visible inside another surfer draft.
- [ ] Add false-negative feedback action.
  - Operator can mark approximate time range, moment type, why good, optional screenshot/note.
- [ ] Separate labels by purpose.
  - Safety labels feed gates: mixed subject, wrong person, duplicate athlete, cut too early, missing evidence.
  - Taste labels feed ranker: boring, weak moment, missed high-value moment, bad pacing.

## Phase 3 — Build baseline metrics

- [ ] Compute run-level metrics:
  - [ ] `draft_count`
  - [ ] `approved_without_reedit_rate`
  - [ ] `review_required_rate`
  - [ ] `mixed_subject_rate`
  - [ ] `duplicate_athlete_rate`
  - [ ] `duplicate_moment_rate`
  - [ ] `cut_too_early_rate`
  - [ ] `source_evidence_coverage_rate`
  - [ ] `sidecar_coverage_rate`
  - [ ] `track_id_coverage_rate`
  - [ ] `drafts_per_real_athlete`
  - [ ] `missed_good_moment_count`
- [ ] Compute draft-level metrics:
  - [ ] visible track count
  - [ ] primary track dominance ratio
  - [ ] non-primary visible duration
  - [ ] non-primary bbox area ratio
  - [ ] wave completion score
  - [ ] source window coverage
  - [ ] candidate value score
  - [ ] confidence of selected moment
- [ ] Create first baseline report from the next diagnostic run.
- [ ] Do not use `number of drafts produced` as primary quality metric.
  - Primary metric: percent of drafts approvable without re-edit.
  - Safety metrics override draft count and speed.

## Phase 4 — Convert failures into replay/eval cases

- [ ] Eval case: duplicate athlete.
  - Expected: same real surfer becomes one collection or weaker duplicate is dropped.
  - Failure: multiple normal standalone drafts share strong athlete/track/source evidence.
- [ ] Eval case: mixed subject.
  - Expected: hard block or review-required with visible-track reason.
  - Failure: normal approvable draft contains significant non-primary track.
- [ ] Eval case: missed good moment.
  - Expected: selected, ranked high, or clear dropped reason.
  - Failure: operator-marked moment missing with no explanation.
- [ ] Eval case: cut-too-early wave.
  - Expected: extend window or review-required.
  - Failure: normal draft cuts before outcome.
- [ ] Add replay runner that evaluates old artifacts without uploading new drafts.
- [ ] No quality fix is complete until it adds or updates replay/eval coverage.

## Phase 5 — Improve hard gates

- [ ] Mixed-subject gate.
  - Rule: if non-primary track is visible above duration/area threshold inside draft window, mark `MULTI_PERSON_CLIP` and block or review-require unless it is an allowed social moment.
- [ ] Duplicate-athlete gate.
  - Rule: if two drafts share strong athlete/track/source evidence, merge, collect, or drop weaker duplicate.
- [ ] Wrong-person gate.
  - Rule: title/person description must match primary track dominance; mismatch becomes review-required.
- [ ] Source-evidence gate.
  - Rule: missing source clip or sidecar evidence blocks or review-requires depending on severity.
- [ ] Each gate must write a human-readable reason for UI, diagnostics, and eval reports.

## Phase 6 — Improve ranking/editorial value

- [ ] Build value ranker separate from safety gates.
  - Inputs: wave length, peak action, outcome, social moment, camera quality, track stability, crop quality, operator labels.
- [ ] Required high-value categories:
  - [ ] long ride
  - [ ] clean takeoff
  - [ ] turn/cutback
  - [ ] fall/recovery
  - [ ] high-five/social moment
  - [ ] crowd/friend interaction
  - [ ] unique camera motion
  - [ ] strong ending
- [ ] Track false negatives.
  - For every missed moment: detected yes/no, candidate yes/no, rank score, dropped reason, fix recommendation.
- [ ] Ranking must combine perception, temporal evidence, source evidence, QA, and feedback; not Gemini score alone.

## Phase 7 — Monitoring and regression control

- [ ] Generate run quality report for every run.
  - Must include metrics, selected drafts, dropped candidates, failures, warnings, artifact links.
- [ ] Store historical metrics by run id, date, commit SHA, model config, and artifact links.
- [ ] Add alert thresholds:
  - [ ] `mixed_subject_rate > 0` in normal drafts -> blocking alert.
  - [ ] `duplicate_athlete_rate > 0` -> blocking alert.
  - [ ] `source_evidence_coverage_rate < 95%` -> warning/block.
  - [ ] approval-without-reedit decreases vs baseline -> investigation.
- [ ] Compare every new run with baseline.
  - Output must say `improved`, `regressed`, or `inconclusive` with metric deltas.
- [ ] Do not deploy a change that improves draft count but regresses safety.

## Phase 8 — UI/operator review improvements

- [ ] Show evidence summary on draft card.
  - Primary athlete/track, visible tracks, mixed-subject risk, duplicate risk, wave completion, source window, selected reason, review-required reason.
- [ ] Show why draft was selected.
- [ ] Show why draft is blocked/review-required.
- [ ] Add structured feedback buttons:
  - [ ] approve
  - [ ] reject
  - [ ] send to re-edit
  - [ ] wrong person
  - [ ] duplicate
  - [ ] mixed people
  - [ ] cut too early
  - [ ] missed good moment
  - [ ] bad crop
  - [ ] boring
- [ ] Preserve structured labels; free text is optional, not enough.

## Phase 9 — Data retention and safety boundaries

- [ ] Do not keep more raw video than needed for debugging/eval.
- [ ] Prefer source-window clips and metadata over duplicating full raw video where possible.
- [ ] Keep enough evidence to reproduce decisions: diagnostics artifact, sidecar, draft metadata, source window, candidate ledger, labels.
- [ ] System may suggest fixes, but production behavior changes require PR, CI, and real-run validation.
- [ ] Separate monitoring data from curated eval data.

## Phase 10 — Implementation order

- [x] Pipeline can produce real drafts.
- [x] Perception backend exists and can run in the production workflow.
- [x] Diagnostics artifact support was added through PR #136.
- [ ] Run one diagnostic pipeline run after diagnostics artifact support is on main.
- [ ] Download and inspect `pipeline-diagnostics-<run_id>`.
- [ ] Build first real-run evaluation report.
- [ ] Convert duplicate-surfer and mixed-subject examples into permanent eval cases.
- [ ] Strengthen mixed-subject gate.
- [ ] Strengthen duplicate-athlete/dedup gate.
- [ ] Add missed-good-moment/recall tracking.
- [ ] Add baseline comparison report/dashboard.

## Definition of done for the whole loop

- [ ] Every draft has a decision trace.
- [ ] Every dropped candidate has a dropped reason.
- [ ] Every operator feedback action becomes a structured label.
- [ ] Every real failure becomes a replay/eval case.
- [ ] Every PR claiming quality improvement runs replay/eval cases.
- [ ] Every real run generates a quality report.
- [ ] Metrics compare new runs against baseline.
- [ ] Safety gates block/review-require mixed-subject, duplicate-athlete, wrong-person, and cut-too-early drafts.
- [ ] Ranking learns taste without weakening safety gates.
- [ ] The system never claims improvement only because more drafts were produced.

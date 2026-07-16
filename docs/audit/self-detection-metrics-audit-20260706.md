# Self-detection metrics audit — 2026-07-06

Companion to `docs/audit/self-learning-loop-audit-20260706.md`.

Goal: define metrics that let SportReel detect likely mistakes, bugs, regressions, and bad runs automatically, before the operator has to point them out.

Core idea from the official docs: production ML systems should capture inputs/outputs, compare them to baselines, compute monitoring signals, set thresholds, and alert on violations. For SportReel, the production data is not only model input/output. It is also sidecars, track evidence, draft metadata, source windows, QA flags, operator actions, and pipeline runtime behavior.

Official references:
- AWS SageMaker Model Monitor: data capture, baselines, monitoring schedules, quality metrics, violations, alerts.
- Azure ML monitoring: production inference data, reference data, data drift, prediction drift, data quality, feature attribution drift, model performance, thresholds.
- Google Cloud Model Monitoring: input/output drift, feature attribution, skew/drift thresholds, distribution distance scores.
- OpenTelemetry: metrics, logs, traces, and events as signals for system behavior.
- OpenAI Evals: expected behavior must become reusable eval cases, not one-off manual judgment.

## Metric families to implement

### 1. Data integrity / data quality metrics

These catch broken artifacts and impossible metadata.

- [ ] `sidecar_missing_rate`
  - Percent of source videos or drafts without a `.perception.json` sidecar when perception is required.
  - Alert: any missing sidecar in required mode.

- [ ] `sidecar_schema_error_rate`
  - Percent of sidecars that fail schema validation.
  - Alert: any schema error in production.

- [ ] `track_id_missing_rate`
  - Percent of detections without `track_id`.
  - Alert: any production detection without track id.

- [ ] `bbox_out_of_bounds_rate`
  - Percent of bboxes outside frame bounds or with invalid geometry.
  - Alert: above 0 for production sidecars.

- [ ] `invalid_time_window_rate`
  - Percent of candidates/drafts with negative duration, end before start, or source window outside video duration.
  - Alert: above 0.

- [ ] `artifact_upload_missing_rate`
  - Percent of runs without diagnostics artifact, source evidence clip, or expected draft metadata.
  - Alert: above 0 for diagnostic runs.

### 2. Perception/input drift metrics

These catch when the detector/tracker behaves differently from previous healthy runs.

- [ ] `detections_per_minute_drift`
  - Compare detections per minute against baseline using distribution distance.
  - Alert: large deviation from baseline.

- [ ] `tracks_per_minute_drift`
  - Compare number of unique tracks per minute against baseline.
  - Alert: too high can mean false positives; too low can mean missed people.

- [ ] `confidence_distribution_drift`
  - Compare detection confidence distribution against baseline.
  - Alert: sudden drop in median/p10 confidence or strong distribution shift.

- [ ] `bbox_area_distribution_drift`
  - Compare bbox area ratios against baseline.
  - Alert: very small/large shift can indicate bad model scale, crop issue, or wrong source resolution.

- [ ] `track_fragmentation_rate`
  - Average number of track ids per apparent athlete/session window.
  - Alert: rising fragmentation means same person may be split into many drafts.

- [ ] `track_duration_distribution_drift`
  - Compare track duration distribution against previous healthy runs.
  - Alert: many short tracks can indicate unstable tracking.

- [ ] `primary_track_dominance_distribution`
  - Distribution of primary track dominance ratio in selected drafts.
  - Alert: low dominance in normal drafts indicates likely mixed-subject clips.

### 3. Output/prediction drift metrics

These catch unexpected changes in final outputs even without labels.

- [ ] `draft_count_drift`
  - Compare draft count per input minute against baseline.
  - Alert: sudden spike or drop.

- [ ] `draft_type_distribution_drift`
  - Compare distribution of draft categories/titles/event types.
  - Alert: system suddenly outputs mostly one class/person/style.

- [ ] `review_required_rate_drift`
  - Compare review-required percentage against baseline.
  - Alert: drop to near zero can mean gates stopped firing; spike can mean perception or QA degraded.

- [ ] `normal_draft_with_warning_rate`
  - Percent of drafts marked normal while containing warning indicators.
  - Alert: above 0 for critical warnings.

- [ ] `title_track_mismatch_rate`
  - Draft title/description does not match dominant track evidence.
  - Alert: any strong mismatch should be review-required.

### 4. Built-in invariant violation metrics

These let the system say: “this looks wrong” even with no human label.

- [ ] `mixed_subject_violation_rate`
  - Normal drafts where a non-primary track is visible for more than threshold duration or bbox-area ratio.
  - Alert: above 0.

- [x] `duplicate_athlete_violation_rate` — implemented 2026-07-16, see `docs/audit/self-detection-metrics-completion-20260716.md`.
  - Multiple normal drafts share strong athlete/track/source evidence.
  - Alert: above 0.

- [ ] `duplicate_moment_violation_rate`
  - Multiple drafts share same event fingerprint/source time overlap.
  - Alert: above 0.

- [ ] `cut_too_early_violation_rate`
  - Draft ends before expected wave outcome or before ride-end evidence.
  - Alert: above 0 for normal drafts.

- [ ] `source_evidence_missing_violation_rate`
  - Normal drafts without source evidence clip/window metadata.
  - Alert: above 0.

- [ ] `no_drafts_with_candidates_rate`
  - Runs where candidates exist but no drafts are produced.
  - Alert: any occurrence.

- [ ] `draft_without_decision_trace_rate`
  - Drafts without candidate ledger link, selection reason, or dropped-candidate context.
  - Alert: above 0.

### 5. Delayed ground-truth/model quality metrics

These use operator actions when available, but still run automatically once labels arrive.

- [ ] `approval_without_reedit_rate`
  - Primary product-quality metric.
  - Alert: drop compared with baseline.

- [ ] `reedit_rate_by_reason`
  - Counts re-edit reasons by structured label.
  - Alert: any rising blocking label.

- [ ] `operator_reject_rate`
  - Percent rejected by operator.
  - Alert: spike vs baseline.

- [ ] `false_positive_gate_rate`
  - Operator approves drafts that gates marked as blocked/review-required.
  - Alert: high rate means gate is too strict.

- [ ] `false_negative_gate_rate`
  - Operator labels a normal draft as mixed/duplicate/wrong/cut-too-early.
  - Alert: any blocking false negative becomes eval case.

### 6. Feature attribution / decision-cause drift

These catch when the system changes why it selects drafts.

- [ ] `selection_reason_distribution_drift`
  - Compare reasons such as long ride, peak action, social moment, wave outcome, stable track.
  - Alert: sudden dominance of one reason.

- [ ] `perception_feature_usage_rate`
  - Percent of selected drafts whose decision used track/bbox/source evidence.
  - Alert: drop means selection may rely too much on Gemini description.

- [ ] `qa_signal_usage_rate`
  - Percent of selected drafts where QA/review-required signals were evaluated and stored.
  - Alert: drop means QA path may be bypassed.

- [ ] `ranker_input_missing_rate`
  - Missing inputs needed by ranker: wave score, track stability, source evidence, candidate value.
  - Alert: above 0 for required fields.

### 7. Operational health metrics

These catch bugs in the pipeline itself.

- [ ] `producer_timeout_rate`
  - Perception producer timeouts per run.
  - Alert: above 0.

- [ ] `dependency_autoupdate_rate`
  - Runtime logs contain dependency auto-install/update messages.
  - Alert: above 0; dependencies should be installed before run.

- [ ] `stage_retry_count`
  - Number of retries per stage.
  - Alert: above baseline or repeated same-stage retry.

- [ ] `stage_duration_p95`
  - p95 runtime per stage: storage, sidecar generation, Gemini analysis, crop/render, upload.
  - Alert: significant increase against baseline.

- [ ] `artifact_generation_failure_rate`
  - Missing diagnostics, draft metadata, source clips, or sidecars.
  - Alert: above 0.

- [ ] `storage_operation_failure_rate`
  - Failed upload/download/list operations.
  - Alert: above 0.

## Automatic bug classification rules

- [ ] `BUG_MIXED_SUBJECT_LIKELY`
  - Trigger when a normal draft has non-primary visible track above threshold.

- [ ] `BUG_DUPLICATE_ATHLETE_LIKELY`
  - Trigger when two normal drafts share strong athlete/track/source evidence.

- [ ] `BUG_TRACKING_DEGRADED_LIKELY`
  - Trigger when confidence drops, track fragmentation rises, or track duration collapses vs baseline.

- [ ] `BUG_SELECTION_BYPASSED_EVIDENCE`
  - Trigger when selected drafts lack sidecar/decision trace/source evidence.

- [ ] `BUG_QA_GATE_BYPASSED`
  - Trigger when warning/review-required signals exist but draft remains approvable as normal.

- [ ] `BUG_RECALL_UNKNOWN`
  - Trigger when candidate ledger or dropped-candidate reasons are missing, because the system cannot prove recall.

- [ ] `BUG_RUNTIME_ENVIRONMENT`
  - Trigger on dependency auto-update, missing operator such as `torchvision.ops.nms`, producer timeout, or missing artifact upload.

## Threshold policy

- [ ] Hard-block thresholds:
  - `mixed_subject_violation_rate > 0`
  - `duplicate_athlete_violation_rate > 0`
  - `draft_without_decision_trace_rate > 0`
  - `source_evidence_missing_violation_rate > 0` for normal drafts
  - `sidecar_schema_error_rate > 0`

- [ ] Warning thresholds:
  - detection confidence median drops materially vs baseline.
  - track fragmentation rises materially vs baseline.
  - review-required rate changes sharply vs baseline.
  - draft count per minute changes sharply vs baseline.
  - stage duration p95 regresses materially.

- [ ] Inconclusive thresholds:
  - missing candidate ledger.
  - missing dropped reasons.
  - missing diagnostics artifact.
  - missing source window metadata.

## Report requirements

- [ ] Every diagnostic run must output `run_quality_report.json`.
- [ ] Report must include metric values, baselines, deltas, thresholds, alert status, and bug classifications.
- [ ] Report must explicitly say one of: `pass`, `fail`, `regressed`, or `inconclusive`.
- [ ] `inconclusive` is not allowed to be treated as success.
- [ ] Every automatic bug classification must point to the draft/candidate/source window/sidecar evidence that triggered it.

## Implementation order for self-detection

- [ ] First, generate metrics from the diagnostics artifact and sidecars.
- [ ] Second, implement invariant metrics that do not require human labels: mixed subject, duplicate athlete, duplicate moment, missing trace, missing evidence.
- [ ] Third, implement drift metrics against the first healthy baseline: confidence, track count, draft count, review-required rate, decision reasons.
- [ ] Fourth, implement delayed-label quality metrics from operator feedback.
- [ ] Fifth, wire automatic bug classifications into the run report and UI.
- [ ] Sixth, make any blocking bug classification prevent normal approval.

## Definition of done

- [ ] The system can mark a run as failed or inconclusive without operator feedback.
- [ ] The system can identify likely mixed-subject and duplicate-athlete bugs from evidence alone.
- [ ] The system can detect perception degradation from distribution drift.
- [ ] The system can detect output regressions from draft/review/selection drift.
- [ ] The system can detect missing observability as a failure, not as success.
- [ ] The system can turn every automatic bug classification into a replay/eval case.

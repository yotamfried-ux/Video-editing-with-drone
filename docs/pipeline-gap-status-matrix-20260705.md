# Pipeline Gap Status Matrix — 2026-07-05

Companion audit file for `docs/pipeline-state-reconciliation-20260705.md`.

This matrix maps every known quality gap to the desired behavior, current state, merged PRs, validation level, status, and next action.

Status values:

- `Closed by contract`: implementation exists and targeted contract/CI passed.
- `Partial`: guardrail/foundation exists, but desired production behavior is not fully implemented.
- `Open`: known product failure still appears or core implementation is missing.
- `Pending real-run validation`: implementation exists, but real draft output has not proven the invariant.

| Gap ID | Desired behavior | Current state | PRs merged | Validation level | Status | Next action |
|---|---|---|---|---|---|---|
| PQ-001 | Deterministic perception foundation exists for bbox/confidence/track metadata. | CV schema and adapter exist, but production pipeline still does not run a real detector/tracker as source of truth. | #88 | Contract/CI only | Partial | Build production detector/tracker pass and attach detections to candidates. |
| PQ-002 | Identity clustering uses stable perception evidence and fails safe. | Identity fail-safe and real identity gate exist, but similar surfers still leak without stable tracker data. | #90, #99, #106 | Contract/CI + real run still failing | Partial | Add run-level athlete canonicalization and same-clip multi-person detection. |
| PQ-003 | Crop/framing uses bbox/track center rather than Gemini hints. | BBox-driven crop guard exists when bbox data is available; Gemini-only events still keep fallback behavior. | #89 | Contract/CI only | Partial | Feed production detections into crop pipeline and flag missing detection. |
| PQ-004 | Pipeline run processes only intended batch/session. | R2 batch isolation exists. | #91 | Contract/CI | Closed by contract | Verify in normal upload/start flow during next multi-file batch test. |
| PQ-005 | Same physical moment is not duplicated across sources. | Cross-source guard exists, but duplicate athlete/draft still appears at person level. | #93, #100, #102 | Contract/CI + real run still shows duplicates | Partial | Add athlete-level canonicalization, not only event/window dedup. |
| PQ-006 | Weak filler events do not become normal drafts. | Parser/runtime weak moment guard exists. | #94 | Contract/CI | Pending real-run validation | Use candidate ledger to confirm good moments are not falsely dropped. |
| PQ-007 | Event windows include setup, peak/action, outcome or are flagged. | Window guard and cut-window guard exist, but wave completion still cannot be measured confidently. | #95, #101, #106 | Contract/CI + real run still uncertain | Partial | Add `wave_completion_score` and boundary evidence. |
| PQ-008 | Editor climax/teaser uses composite quality, not Gemini score alone. | Narrative quality guard exists. | #96 | Contract/CI | Pending real-run validation | Use value labels and ledger to evaluate false negatives and social moments. |
| PQ-009 | Critical QA defects do not look like normal approvals. | QA diagnostics/fail-closed exist, but UI still shows normal Approve for QA-labelled drafts. | #97, #103, #104, #105 | Contract/CI + real UI gap | Partial | Add UI gating and blocking-reason visibility. |
| PQ-010 | Draft output is reconstructable from metadata. | Draft diagnostic artifact exists, but latest run had no downloadable Actions artifacts and UI metadata is insufficient. | #98 | Contract/CI | Partial | Persist candidate ledger and expose metadata in operator UI. |
| REAL-ID-001 | Mixed athletes do not reach normal review drafts. | Real identity gate exists, but latest run still showed people appearing in wrong clips. | #99, #106 | Real run still failing | Partial | Add same-source multi-person detection and tracker-backed identity. |
| REAL-DUP-001 | Repeated segment does not appear twice in one draft. | Final duplicate guard exists. | #100 | Contract/CI | Pending real-run validation | Confirm with candidate/output ledger on next run. |
| REAL-CUT-001 | Surf waves are not cut before outcome. | Cut-window and surf ride guards exist, but operator still cannot confirm every wave reaches satisfying finish. | #101, #106 | Real run still uncertain | Partial | Add wave completion confidence and source boundary evidence. |
| REAL-QA-001 | QA sees edit/source context, not only final reel. | Context QA sends edit/source JSON. | #102, #104 | Contract/CI | Closed by contract | Verify UI exposes QA reasons to operator. |
| REAL-DUP-002 | Duplicate rendered drafts under different descriptions are blocked. | Run-level context dedup exists, but same surfer still appears in multiple drafts. | #102 | Real run still failing at athlete level | Partial | Extend from draft-window dedup to athlete canonicalization. |
| REAL-QA-002 | QA uncertainty fails closed. | Skipped/unavailable QA becomes review-required FAIL. | #103 | Contract/CI | Closed by contract | Ensure UI blocks normal approval for review-required drafts. |
| REAL-QA-004 | QA can compare final draft against source-window video evidence. | Source evidence clips are uploaded when available and fail-closed when upload fails. | #105 | Contract/CI | Pending real-run validation | Persist whether each draft had `source_evidence_visual_uploaded`. |
| REAL-WAVE-001 | Surf ride is atomic editorial unit. | Surf fragments normalize into `surf_ride`; missing boundaries are flagged. | #106 | Contract/CI + real run improved but not fully solved | Partial | Add wave completion scoring and candidate ledger. |
| REAL-ID-003 | Similar surfers inside source windows are not silently merged. | Identity uncertainty can be surfaced, but no production tracker proves same-source continuity. | #106 | Real run still failing | Partial | Add same-clip multi-person detection and stable athlete registry. |
| REAL-ID-004 | Single-athlete draft does not contain another visible athlete unless intentional. | Real output shows this still happens. | none yet | Real run failure | Open | Add multi-person detection and `MULTI_PERSON_CLIP` diagnostics. |
| REAL-WAVE-002 | Every surf draft exposes wave completion confidence. | No `wave_completion_score` exists yet. | none yet | Not implemented | Open | Add wave completion scoring and boundary evidence. |
| REAL-VALUE-001 | System learns what is worth showing from feedback and examples. | No feedback dataset, ranking ledger, replay eval, or value labels yet. | none yet | Not implemented | Open | Add value labels, feedback events, eval set, and candidate ranker. |
| REAL-RECALL-001 | Good moments are not silently dropped. | High-five/social moment disappeared without trace. | none yet | Real run failure | Open | Add candidate decision ledger and false-negative feedback path. |
| REAL-ATHLETE-001 | Same athlete maps to stable `athlete_id` and does not create many standalone drafts. | Same surfer still appears in multiple drafts. | none yet | Real run failure | Open | Add run-level athlete canonicalization and collection policy. |
| REAL-UI-001 | QA/review-required drafts cannot be approved like normal drafts. | UI screenshot shows QA-labelled draft still has Approve. | none yet | Real UI failure | Open | Disable/demote Approve and show blocking QA reasons. |
| REAL-UPLOAD-001 | Upload button supports selecting/uploading many videos in one action. | API initializes one upload session per filename; frontend multi-select/parallel behavior is not proven and rate limit may block big batches. | none yet | Not validated | Open | Add multi-file input, concurrent upload, shared batch id, per-file progress, and contract test. |
| REAL-TRACE-001 | Every candidate has decision trace. | No complete run-level candidate ledger exists. | none yet | Not implemented | Open | Add candidate ledger persisted with draft metadata and/or artifacts. |

## Immediate implication

The next implementation PR should start with `REAL-TRACE-001` and `REAL-VALUE-001`:

1. Add candidate decision ledger.
2. Add operator feedback/value labels.
3. Persist selected/dropped/merged/QA-failed reasons.
4. Then use the ledger to fix `REAL-ATHLETE-001`, `REAL-ID-004`, `REAL-WAVE-002`, and `REAL-UPLOAD-001` with evidence instead of guessing.

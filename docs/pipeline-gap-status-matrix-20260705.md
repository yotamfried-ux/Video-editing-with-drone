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
| PQ-002 | Identity clustering uses stable perception evidence and fails safe. | Identity fail-safe and real identity gate exist, and #109 adds deterministic athlete IDs/merge evidence, but similar surfers still require tracker-backed real-run validation. | #90, #99, #106, #109 | Contract/CI + prior real run still failing | Partial | Validate athlete canonicalization on the next real run and add same-clip multi-person detection. |
| PQ-003 | Crop/framing uses bbox/track center rather than Gemini hints. | BBox-driven crop guard exists when bbox data is available; Gemini-only events still keep fallback behavior. | #89 | Contract/CI only | Partial | Feed production detections into crop pipeline and flag missing detection. |
| PQ-004 | Pipeline run processes only intended batch/session. | R2 batch isolation exists. | #91 | Contract/CI | Closed by contract | Verify in normal upload/start flow during next multi-file batch test. |
| PQ-005 | Same physical moment is not duplicated across sources. | Cross-source guard exists, and #109 adds athlete-level duplicate evidence only when strong IDs match; person-level duplicates still need real-run proof. | #93, #100, #102, #109 | Contract/CI + prior real run still shows duplicates | Partial | Validate athlete-level canonicalization against actual draft outputs. |
| PQ-006 | Weak filler events do not become normal drafts. | Parser/runtime weak moment guard exists. | #94 | Contract/CI | Pending real-run validation | Use candidate ledger to confirm good moments are not falsely dropped. |
| PQ-007 | Event windows include setup, peak/action, outcome or are flagged. | Window guard and cut-window guard exist, but wave completion still cannot be measured confidently. | #95, #101, #106 | Contract/CI + real run still uncertain | Partial | Add `wave_completion_score` and boundary evidence. |
| PQ-008 | Editor climax/teaser uses composite quality, not Gemini score alone. | Narrative quality guard exists, and #108 adds value labels/feedback schema but no ranker or replay eval yet. | #96, #108 | Contract/CI only | Partial | Build value eval set and candidate ranker using ledger/feedback events. |
| PQ-009 | Critical QA defects do not look like normal approvals. | QA diagnostics/fail-closed exist, but UI still shows normal Approve for QA-labelled drafts. | #97, #103, #104, #105 | Contract/CI + real UI gap | Partial | Add UI gating and blocking-reason visibility. |
| PQ-010 | Draft output is reconstructable from metadata. | Draft diagnostic artifact exists and #108 adds candidate ledger metadata, but latest real run had no downloadable Actions artifacts and UI metadata is still insufficient. | #98, #108 | Contract/CI | Partial | Verify candidate ledger in real artifacts and expose metadata in operator UI. |
| REAL-ID-001 | Mixed athletes do not reach normal review drafts. | Real identity gate exists; #109 adds run-level athlete IDs, but latest real run still showed people appearing in wrong clips and same-clip leakage is not solved. | #99, #106, #109 | Contract/CI + prior real run still failing | Partial | Add same-source multi-person detection and tracker-backed identity. |
| REAL-DUP-001 | Repeated segment does not appear twice in one draft. | Final duplicate guard exists. | #100 | Contract/CI | Pending real-run validation | Confirm with candidate/output ledger on next run. |
| REAL-CUT-001 | Surf waves are not cut before outcome. | Cut-window and surf ride guards exist, but operator still cannot confirm every wave reaches satisfying finish. | #101, #106 | Real run still uncertain | Partial | Add wave completion confidence and source boundary evidence. |
| REAL-QA-001 | QA sees edit/source context, not only final reel. | Context QA sends edit/source JSON. | #102, #104 | Contract/CI | Closed by contract | Verify UI exposes QA reasons to operator. |
| REAL-DUP-002 | Duplicate rendered drafts under different descriptions are blocked. | Run-level context dedup exists; #109 adds stable athlete IDs and duplicate evidence for strong matches, but prior real run still failed at athlete level. | #102, #109 | Contract/CI + pending real-run validation | Partial | Validate strong-match athlete merging and collection behavior on real outputs. |
| REAL-QA-002 | QA uncertainty fails closed. | Skipped/unavailable QA becomes review-required FAIL. | #103 | Contract/CI | Closed by contract | Ensure UI blocks normal approval for review-required drafts. |
| REAL-QA-004 | QA can compare final draft against source-window video evidence. | Source evidence clips are uploaded when available and fail-closed when upload fails. | #105 | Contract/CI | Pending real-run validation | Persist whether each draft had `source_evidence_visual_uploaded`. |
| REAL-WAVE-001 | Surf ride is atomic editorial unit. | Surf fragments normalize into `surf_ride`; missing boundaries are flagged. | #106 | Contract/CI + real run improved but not fully solved | Partial | Add wave completion scoring and candidate ledger. |
| REAL-ID-003 | Similar surfers inside source windows are not silently merged. | Identity uncertainty can be surfaced, and #109 avoids weak/description-only canonical merges, but no production tracker proves same-source continuity. | #106, #109 | Contract/CI + prior real run still failing | Partial | Add same-clip multi-person detection and stable tracker-backed athlete registry. |
| REAL-ID-004 | Single-athlete draft does not contain another visible athlete unless intentional. | Real output shows this still happens. | none yet | Real run failure | Open | Add multi-person detection and `MULTI_PERSON_CLIP` diagnostics. |
| REAL-WAVE-002 | Every surf draft exposes wave completion confidence. | No `wave_completion_score` exists yet. | none yet | Not implemented | Open | Add wave completion scoring and boundary evidence. |
| REAL-VALUE-001 | System learns what is worth showing from feedback and examples. | #108 adds value labels and operator feedback event schema, but there is no feedback dataset, replay eval, or product-value ranker yet. | #108 | Contract/CI only | Partial | Build eval set, replay grader, and value ranker from reviewed runs. |
| REAL-RECALL-001 | Good moments are not silently dropped. | #108 adds candidate decision ledger/false-negative schema, but the high-five/social miss has not been re-run or explained yet. | #108 | Contract/CI + pending real-run validation | Pending real-run validation | Inspect next run ledger for detected/selected/dropped social moments. |
| REAL-ATHLETE-001 | Same athlete maps to stable `athlete_id` and does not create many standalone drafts. | #109 assigns stable `athlete_id`, merges only strong same-athlete evidence, marks merged same-athlete groups as collections, and emits duplicate evidence; not real-run validated yet. | #109 | Contract/CI only | Closed by contract | Validate on next real run and expand to tracker-backed canonicalization. |
| REAL-UI-001 | QA/review-required drafts cannot be approved like normal drafts. | UI screenshot shows QA-labelled draft still has Approve. | none yet | Real UI failure | Open | Disable/demote Approve and show blocking QA reasons. |
| REAL-UPLOAD-001 | Upload button supports selecting/uploading many videos in one action. | API initializes one upload session per filename; frontend multi-select/parallel behavior is not proven and rate limit may block big batches. | none yet | Not validated | Open | Add multi-file input, concurrent upload, shared batch id, per-file progress, and contract test. |
| REAL-TRACE-001 | Every candidate has decision trace. | #108 adds `candidate_decision_ledger` and feedback schema to draft diagnostics, including selected/review-required/QA-blocked/dropped entries where surfaced by the artifact. | #108 | Contract/CI only | Pending real-run validation | Verify ledger completeness in the next real run artifacts and UI metadata. |

## Immediate implication

The ledger foundation from `REAL-TRACE-001` / `REAL-VALUE-001` is now implemented by contract, so the active repair order is:

1. Finish and merge `REAL-ATHLETE-001` by contract.
2. Add same-clip multi-person detection for `REAL-ID-004`.
3. Add `wave_completion_score` and boundary evidence for `REAL-WAVE-002`.
4. Add operator UI gating for `REAL-UI-001`.
5. Add multi-video batch upload for `REAL-UPLOAD-001`.
6. Validate all quality claims with a real pipeline run only after audit/gap files remain synchronized.

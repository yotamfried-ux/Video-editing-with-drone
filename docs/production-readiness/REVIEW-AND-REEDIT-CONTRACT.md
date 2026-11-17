# Review, re-edit and approval contract (binding, owner clarification of cycle 6)

**Status of the operator Review screen: complete as it is.** It is not rebuilt and loses no function. It is not a
pair-comparison tool, and no separate approval system is created. Two earlier directions are withdrawn:
the "owner REVIEW queue tool / main screen for comparing athlete pairs", and the interim wording that rejection
must never reach re-edit. The existing screen and its re-edit integration stay exactly as shipped.

## Intended flow

1. The pipeline identifies athletes, selects rides, edits and renders a full reel.
2. Automatic QA checks the reel. On a defect it re-edits automatically with the defect details
   (`pipeline/orchestrator.py::_qa_gate`, `QA_MAX_RETRIES=2`, no-op re-edits skipped, QA re-run after every re-edit).
3. Only a reel that passed every required QA gate can be approved: the approval API refuses anything whose
   authoritative `draft_publishability` row is not `publishable` + `qa_evidence_recorded` + `PASS` + no technical issue,
   and anything with an active re-edit task.
4. On the Review screen the owner watches the full reel and chooses: **approve** (-> Discover), **re-edit** (writes
   what was wrong; the reel goes to another processing run), or **reject** (not published).
5. The re-edit option stays available even for a reel QA passed: it is the manual correction path for what QA missed.

## Two separate, controlled re-edit routes (verified, not changed)

| | Automatic QA repair | Manual owner re-edit |
|---|---|---|
| Trigger | final QA finds a blocking defect, inside the run | owner presses re-edit on Review |
| Writer | pipeline `_qa_gate` | web-api `/api/operator/reprocess` |
| Bound | `QA_MAX_RETRIES=2` per reel, no-op skipped | `reprocess_requests.max_attempts=3`, one active task per draft |
| State | none persisted; reel flagged if still failing | `reprocess_requests`: `qa_blocked -> pending -> queued -> done / reprocessed_unverified / failed_max_attempts` |
| Crossing | the pipeline cannot move `qa_blocked -> pending`; only the operator API can (`pipeline/repair_lifecycle.py::ALLOWED`) | closure `done` needs an athlete/output-bound verified verdict (`pipeline/reprocess_binding.py`) |

Evidence: `test_repair_lifecycle_contract`, `test_reprocess_binding_contract`, `test_qa_reedit_loop_contract`,
`test_qa_reedit_task_verifier_contract`, `test_operator_review_gate_contract`, `test_qa_reedit_noop_contract`
(all pass on this head).

## Re-edited reel: fresh QA and fresh approval

* The re-render runs final QA again and writes its own `draft_publishability` row.
* Approval is an explicit operator action, never stored state: an earlier approval cannot carry over to a new file.
* An active re-edit task (`qa_blocked/pending/queued`) blocks approval.
* **Gap found and closed this cycle.** R2 REVIEW objects are keyed by draft name (`review/<name>`), so a re-edit
  replaces the bytes under the same storage id while the previous run's PASS row stayed valid until the new run wrote
  its own. In that window, or if the new row's write failed, the approval API could approve bytes final QA had not
  graded. `integrations/r2_storage.upload_draft` now first revokes the key's authority
  (`supabase_uploader.revoke_draft_publishability`: not publishable, no QA evidence, a reason the Review screen shows);
  if the revocation cannot be recorded, the object is not replaced. Contract:
  `scripts/test_review_replacement_invalidation_contract.py` (red before the change, green after).
  No web-api, mobile or schema change.

## Approved file <-> delivered file (unchanged)

Approve moves `review/<name>` to `approved/` and dispatches delivery with `approved_file_id`; delivery downloads that
object and publishes it to Discover. Not touched.

## Identity uncertainty

Handled inside the pipeline. An unconfirmed identity merge is withheld automatically (fail closed). The structured
identity requests and the optional decisions file from cycle 5 remain internal records; no screen is built on them,
and nothing in the product depends on the owner comparing pairs.

## Cycle 6 focus

Raise the share of correct reels that pass on the first attempt (detection, cuts, QA), measured with the GT scorecard
against both baselines. Open items: end-of-ride tails (0108-type), starts that are not source-limited (0115-type),
real end-to-end time of the concurrent consensus calls.

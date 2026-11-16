"""QA repair lifecycle (RC-06): the spec's state machine over the existing reprocess_requests.status values.

    DETECTED -> CLASSIFIED -> REPAIR_READY -> PROCESSING -> AWAITING_QA -> VERIFIED_RESOLVED
    alternates: REVIEW_REQUIRED, SOURCE_LIMITED, RETRY_EXHAUSTED, REPROCESSED_UNVERIFIED, HARD_REJECTED

No new status column is needed: each stored status maps to one spec state (AWAITING_QA is the in-run span between
render and closure, inside `queued`). Every transition the pipeline writes is checked here first, so a code path
cannot, for example, close a request that was never claimed, or move a terminal request again. Terminal states
carry their evidence in repair_verdict.
"""
from __future__ import annotations

from typing import Any

# stored status -> spec state
STATE_OF_STATUS = {
    "qa_blocked": "CLASSIFIED",            # detected by the QA gate, defects classified, waiting for the operator
    "pending": "REPAIR_READY",             # operator sent it (or recovery re-queued it)
    "queued": "PROCESSING",                # claimed by one run (render, final QA, closure)
    "done": "VERIFIED_RESOLVED",           # athlete/output-bound verdict verified
    "reprocessed_unverified": "REPROCESSED_UNVERIFIED",
    "failed_max_attempts": "RETRY_EXHAUSTED",
    "source_not_found": "SOURCE_LIMITED",
    "cancelled": "HARD_REJECTED",          # removed by an operator / storage cleanup
}
TERMINAL = {"done", "reprocessed_unverified", "failed_max_attempts", "source_not_found", "cancelled"}

# stored transitions the pipeline and the operator API may perform
ALLOWED = {
    ("qa_blocked", "qa_blocked"),           # refresh of an unsent task (compare-and-swap)
    ("qa_blocked", "pending"),              # operator: send to re-edit (web-api)
    ("qa_blocked", "failed_max_attempts"),  # operator API: attempts exhausted
    ("pending", "queued"),                  # claim by exactly one run
    ("pending", "source_not_found"),        # sources gone
    ("queued", "done"),                     # verified repair (owner run only)
    ("queued", "reprocessed_unverified"),   # anything less than verified
    ("queued", "pending"),                  # recovery: owner run ended without closure, attempts remain
    ("queued", "failed_max_attempts"),      # recovery: attempts exhausted
}


class IllegalTransition(ValueError):
    pass


def state(status: str | None) -> str:
    return STATE_OF_STATUS.get(str(status or ""), "UNKNOWN")


def check_transition(old: str, new: str) -> None:
    """Raise when the pipeline would write a transition the lifecycle does not allow."""
    if (old, new) not in ALLOWED:
        raise IllegalTransition(f"reprocess lifecycle: {old} -> {new} is not allowed")


def is_terminal(status: str | None) -> bool:
    return str(status or "") in TERMINAL


def backlog_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts per spec state and per stored status, and the historical tasks never attempted.

    Historical rows are classified, never closed: a qa_blocked row with attempt_count 0 is an operator decision
    that was never taken, not a repaired or failed defect.
    """
    by_state: dict[str, int] = {}
    by_status: dict[str, int] = {}
    never_attempted = 0
    for row in rows or []:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_state[state(status)] = by_state.get(state(status), 0) + 1
        if status == "qa_blocked" and not int(row.get("attempt_count") or 0):
            never_attempted += 1
    return {"total": len(rows or []), "by_state": by_state, "by_status": by_status,
            "qa_blocked_never_attempted": never_attempted}

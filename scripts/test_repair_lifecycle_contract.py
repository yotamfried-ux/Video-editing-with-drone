#!/usr/bin/env python3
"""QA repair lifecycle (RC-06, T09/T14): stored statuses map to the spec's states; only allowed transitions."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))

from pipeline import repair_lifecycle as lc  # noqa: E402


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def main() -> int:
    for status in ("qa_blocked", "pending", "queued", "done", "reprocessed_unverified", "failed_max_attempts",
                   "source_not_found", "cancelled"):
        check(lc.state(status) != "UNKNOWN", f"status {status} has no lifecycle state")
    check(lc.state("done") == "VERIFIED_RESOLVED" and lc.state("queued") == "PROCESSING", "state mapping")
    for old, new in (("qa_blocked", "done"), ("pending", "done"), ("done", "queued"), ("done", "pending"),
                     ("reprocessed_unverified", "done"), ("cancelled", "pending"), ("queued", "qa_blocked")):
        try:
            lc.check_transition(old, new)
            raise SystemExit(f"illegal transition {old} -> {new} was allowed")
        except lc.IllegalTransition:
            pass
    for old, new in (("pending", "queued"), ("queued", "done"), ("queued", "reprocessed_unverified"),
                     ("queued", "pending"), ("queued", "failed_max_attempts")):
        lc.check_transition(old, new)
    check(all(lc.is_terminal(s) for s in lc.TERMINAL) and not lc.is_terminal("queued"), "terminal states")
    rows = [{"status": "qa_blocked", "attempt_count": 0}] * 3 + [{"status": "qa_blocked", "attempt_count": 1},
                                                               {"status": "done"}, {"status": "cancelled"}]
    summary = lc.backlog_summary(rows)
    check(summary["qa_blocked_never_attempted"] == 3 and summary["by_state"]["CLASSIFIED"] == 4
          and summary["by_status"]["cancelled"] == 1, f"backlog summary: {summary}")
    # every transition the uploader performs is one the lifecycle allows (the uploader checks before writing)
    source = (ROOT / "integrations" / "supabase_uploader.py").read_text(encoding="utf-8")
    check(source.count("check_transition(") >= 3, "the uploader must check its claim, closure and recovery transitions")
    print("PASS: repair lifecycle (state mapping, allowed transitions, backlog classification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

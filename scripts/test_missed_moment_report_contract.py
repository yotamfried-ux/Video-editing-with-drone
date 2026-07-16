#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from generate_missed_moment_report import build_missed_moment_report

    feedback_rows = [
        {"draft_name": "DRAFT_surfer.mp4", "feedback_event": "MISSING_GOOD_MOMENT", "note": "missed a big turn near the end", "created_at": "2026-07-16T00:00:00Z"},
        {"draft_name": "DRAFT_no_ledger.mp4", "feedback_event": "MISSING_GOOD_MOMENT", "note": "no idea, just a guess", "created_at": "2026-07-16T00:00:00Z"},
        {"draft_name": "DRAFT_surfer.mp4", "feedback_event": "BORING", "note": "", "created_at": "2026-07-16T00:00:00Z"},
        {"draft_name": "DRAFT_surfer.mp4", "feedback_event": "APPROVE", "note": "", "created_at": "2026-07-16T00:00:00Z"},
    ]
    reels_metadata = {
        "DRAFT_surfer.mp4": {
            "diagnostic_artifact": {
                "candidate_decision_ledger": {
                    "entries": [
                        {"candidate_id": "a", "decision": "selected"},
                        {"candidate_id": "b", "decision": "dropped_or_blocked", "type": "big_turn", "score": 7},
                        {"candidate_id": "c", "decision": "dropped_or_blocked", "type": "paddle", "score": 3},
                    ]
                }
            }
        },
    }

    report = build_missed_moment_report(feedback_rows, reels_metadata)
    if report["schema_version"] != "sportreel.missed_moment_report.v1":
        raise SystemExit("schema version missing")
    if report["missed_good_moment_count"] != 2:
        raise SystemExit("missed_good_moment_count should only count MISSING_GOOD_MOMENT rows")
    if report["missed_good_moment_with_ledger_count"] != 1:
        raise SystemExit("only the draft with a persisted ledger should count as with_ledger")
    if report["missed_good_moment_without_ledger_count"] != 1:
        raise SystemExit("the draft without ledger metadata should count as without_ledger")

    surfer_entry = next(e for e in report["entries"] if e["draft_name"] == "DRAFT_surfer.mp4")
    if surfer_entry["dropped_candidate_count"] != 2:
        raise SystemExit("dropped candidate count should exclude the selected entry")
    if not surfer_entry["candidate_ledger_available"]:
        raise SystemExit("candidate ledger availability flag wrong for a draft with metadata")

    no_ledger_entry = next(e for e in report["entries"] if e["draft_name"] == "DRAFT_no_ledger.mp4")
    if no_ledger_entry["candidate_ledger_available"]:
        raise SystemExit("candidate ledger availability flag wrong for a draft with no metadata at all")
    if no_ledger_entry["dropped_candidate_count"] != 0:
        raise SystemExit("a draft with no metadata must not fabricate dropped candidates")

    # Empty feedback must not error and must report zero, not crash on missing keys.
    empty = build_missed_moment_report([], {})
    if empty["missed_good_moment_count"] != 0 or empty["entries"] != []:
        raise SystemExit("empty feedback input should produce a zeroed, empty report")

    print("Missed-moment report contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

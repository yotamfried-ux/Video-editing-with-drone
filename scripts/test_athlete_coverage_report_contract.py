#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_athlete_coverage_report import build_report


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ledger_path = tmp / "ledger.json"
        audit_path = tmp / "audit.json"
        ledger_path.write_text(json.dumps({
            "candidates": [
                {
                    "candidate_id": "a1",
                    "person_id": "player_7",
                    "person_description": "player #7 in red jersey",
                    "selected": True,
                    "discarded": False,
                    "score": 9,
                    "source_window": {"start": 10, "end": 20, "duration": 10},
                },
                {
                    "candidate_id": "a2",
                    "person_id": "player_7",
                    "person_description": "player #7 in red jersey",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "dedup_overlap_lower_score",
                    "score": 7,
                    "source_window": {"start": 11, "end": 20, "duration": 9},
                },
                {
                    "candidate_id": "b1",
                    "person_id": "surfer_B",
                    "person_description": "surfer on blue longboard",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "subject_gated_by_pre_qa_prefilter",
                    "score": 8,
                    "source_window": {"start": 30, "end": 45, "duration": 15},
                },
                {
                    "candidate_id": "c1",
                    "person_id": "player_10",
                    "person_description": "player #10 in white jersey",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "selected_by_selector_not_emitted_as_draft",
                    "score": 8,
                    "source_window": {"start": 50, "end": 61, "duration": 11},
                },
            ]
        }), encoding="utf-8")
        audit_path.write_text(json.dumps({
            "candidates": [
                {"candidate_id": "a2", "discard_cause_detailed": "dedup_overlap_lower_score", "decision_path": ["selector", "dedup"]},
                {"candidate_id": "b1", "discard_cause_detailed": "subject_gated_by_pre_qa_prefilter", "decision_path": ["prefilter_failed"]},
                {"candidate_id": "c1", "discard_cause_detailed": "selected_by_selector_not_emitted_as_draft", "decision_path": ["not_emitted"]},
            ]
        }), encoding="utf-8")

        report = build_report(ledger_path, audit_path)
        summary = report["summary"]
        require(summary["confirmed_athlete_cluster_count"] == 3, f"cluster count wrong: {summary}")
        require(summary["represented_athlete_cluster_count"] == 1, f"represented count wrong: {summary}")
        require(summary["covered_or_explicitly_explained_cluster_count"] == 2, f"accountability count wrong: {summary}")
        require(summary["coverage_gap_cluster_count"] == 1, f"unresolved coverage gap missing: {summary}")
        require(summary["candidate_action_seconds"] == 45.0, f"candidate seconds wrong: {summary}")
        require(summary["selected_action_seconds"] == 10.0, f"selected seconds wrong: {summary}")

        by_id = {item["athlete_cluster_id"]: item for item in report["athletes"]}
        require(by_id["player_7"]["final_outcome"] == "draft_created", f"selected athlete outcome wrong: {by_id}")
        require(by_id["surfer_B"]["final_outcome"] == "target_not_trackable", f"explicit no-output reason wrong: {by_id}")
        require(by_id["surfer_B"]["coverage_requirement_met"] is True, "explicit no-output should satisfy accountability")
        require(by_id["player_10"]["final_outcome"] == "unresolved_selection_path", f"generic reason should remain a gap: {by_id}")
        require(by_id["player_10"]["coverage_requirement_met"] is False, "generic reason must not satisfy accountability")

    runner = (ROOT / "scripts" / "run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")
    for token in [
        "ATHLETE_COVERAGE_FILE",
        "build_athlete_coverage_report.py",
        "athlete_coverage_report.json",
        "append_athlete_coverage_summary_to_report.py",
    ]:
        require(token in runner, f"diagnostics runner missing {token}")

    print("athlete coverage report contract ok")


if __name__ == "__main__":
    main()

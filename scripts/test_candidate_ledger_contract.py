#!/usr/bin/env python3
"""Contract for REAL-TRACE-001 and REAL-VALUE-001 candidate ledger."""
from __future__ import annotations

from pipeline.candidate_ledger import (
    OPERATOR_FEEDBACK_EVENTS,
    VALUE_LABELS,
    build_candidate_decision_ledger,
    infer_value_labels,
    install,
    value_feedback_schema,
)
import pipeline.draft_diagnostics as draft_diagnostics


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    event = {
        "event_id": "wave_001",
        "type": "surf_ride",
        "description": "surfer carves then gives a high five during the wave",
        "score": 9,
        "start": 10.0,
        "end": 31.0,
        "_src": "/tmp/source-a.mp4",
        "track_id": "athlete-7",
        "ride_segment": True,
        "ride_fragment_count": 2,
        "ride_boundary_uncertain": False,
        "bbox_xyxy": [100, 100, 240, 280],
        "visible_ratio": 0.42,
    }
    labels = infer_value_labels(event)
    for expected in ["FULL_RIDE", "SOCIAL_MOMENT", "HIGH_FIVE", "BIG_TURN", "CLEAR_ATHLETE"]:
        assert_true(expected in labels, f"expected {expected} label, got {labels}")

    uncertain = {
        "event_id": "wave_002",
        "type": "surf_ride",
        "description": "uncertain partial ride",
        "start": 40.0,
        "end": 45.0,
        "ride_segment": True,
        "ride_boundary_uncertain": True,
        "identity_uncertain": True,
        "dedup_dropped_duplicates": [{"type": "RIDE_BOUNDARY_UNCERTAIN", "severity": "critical"}],
    }
    ledger = build_candidate_decision_ledger("DRAFT_test.mp4", "surfing", [event, uncertain])
    assert_true(ledger["schema_version"] == "1.0", "ledger schema version missing")
    assert_true(len(ledger["entries"]) == 2, "expected one ledger row per candidate")
    decisions = {row["event_id"]: row["decision"] for row in ledger["entries"]}
    assert_true(decisions["wave_001"] == "selected", "clear full ride should be selected")
    assert_true(decisions["wave_002"] == "selected_review_required", "uncertain ride should require review")
    assert_true(ledger["summary"]["value_label_counts"].get("HIGH_FIVE") == 1, "summary must count high-five label")

    schema = value_feedback_schema()
    for feedback_event in ["APPROVE", "SEND_TO_REEDIT", "MISSING_GOOD_MOMENT", "WRONG_ATHLETE", "CUT_TOO_EARLY", "FALSE_NEGATIVE"]:
        assert_true(feedback_event in schema["operator_feedback_events"], f"missing feedback event {feedback_event}")
    for value_label in ["SOCIAL_MOMENT", "HIGH_FIVE", "FULL_RIDE", "DUPLICATE_ATHLETE", "CUT_TOO_EARLY"]:
        assert_true(value_label in schema["value_labels"], f"missing value label {value_label}")
    assert_true(set(OPERATOR_FEEDBACK_EVENTS).issubset(schema["operator_feedback_events"]), "schema must expose all feedback events")
    assert_true(set(VALUE_LABELS).issubset(schema["value_labels"]), "schema must expose all value labels")

    install()
    artifact = draft_diagnostics.build_diagnostic_artifact("DRAFT_test.mp4", "surfing", [event, uncertain], {"width": 1920, "height": 1080})
    assert_true("candidate_decision_ledger" in artifact, "diagnostic artifact must include candidate ledger")
    assert_true("value_feedback_schema" in artifact, "diagnostic artifact must include feedback schema")
    artifact_ledger = artifact["candidate_decision_ledger"]
    assert_true(artifact_ledger["summary"]["candidate_count"] >= 2, "artifact ledger should include selected candidates")
    assert_true(artifact_ledger["summary"]["value_label_counts"].get("HIGH_FIVE") == 1, "artifact ledger must preserve original event labels")
    assert_true(artifact_ledger["summary"]["value_label_counts"].get("CUT_TOO_EARLY") == 1, "artifact ledger must preserve uncertainty labels")

    with open("scripts/sitecustomize.py", encoding="utf-8") as handle:
        bootstrap = handle.read()
    assert_true("pipeline.candidate_ledger" in bootstrap, "sitecustomize must bootstrap candidate ledger")

    print("candidate ledger contract ok")


if __name__ == "__main__":
    main()

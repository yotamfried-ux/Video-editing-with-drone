#!/usr/bin/env python3
"""Contract for selection decision telemetry."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_selection_decision_audit.py"
spec = importlib.util.spec_from_file_location("build_selection_decision_audit", BUILDER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load {BUILDER_PATH}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
build_audit = module.build_audit


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ledger_path = tmp / "candidate_decision_ledger.json"
        trace_path = tmp / "draft_decision_trace.json"
        log_path = tmp / "run_tracked.log"

        draft_name = "DRAFT_surfer in black shorts on a turquoise longboard_20260709.mp4"
        ledger = {
            "schema_version": "sportreel.candidate_decision_ledger.v1",
            "candidates": [
                {
                    "candidate_id": "selected-459",
                    "draft_id": draft_name,
                    "draft_name": draft_name,
                    "selected": True,
                    "discarded": False,
                    "selection_reason": "selected_for_uploaded_draft",
                    "event_type": "highlight",
                    "score": 7,
                    "source_video": "source.mp4",
                    "source_window": {"start": 459.0, "end": 475.0, "duration": 16.0},
                    "description": "A quick, clean ride with a sharp turn.",
                },
                {
                    "candidate_id": "discarded-480",
                    "person_id": "person_B",
                    "person_description": "surfer in dark swim trunks on a turquoise longboard",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "selected_by_selector_not_emitted_as_draft",
                    "event_type": "highlight",
                    "score": 9,
                    "source_video": "source.mp4",
                    "source_window": {"start": 480.0, "end": 491.0, "duration": 11.0},
                    "description": "Catches a wave and holds a long, clean line with smooth carves.",
                    "unmatched_selector_selection": True,
                },
                {
                    "candidate_id": "discarded-515",
                    "person_id": "person_A",
                    "person_description": "surfer in pink swimsuit on a pink longboard",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "selected_by_selector_not_emitted_as_draft",
                    "event_type": "wave_catch",
                    "score": 8,
                    "source_video": "source.mp4",
                    "source_window": {"start": 515.0, "end": 535.0, "duration": 20.0},
                    "description": "Shares a wave with another surfer while carving.",
                    "unmatched_selector_selection": True,
                },
            ],
        }
        trace = {
            "schema_version": "sportreel.draft_decision_trace.v1",
            "drafts": [
                {
                    "draft_id": draft_name,
                    "draft_name": draft_name,
                    "sport": "surfing",
                    "source_windows": [
                        {
                            "source_video": "source.mp4",
                            "event_type": "highlight",
                            "start": 459.0,
                            "end": 475.0,
                            "duration": 16.0,
                            "score": 7,
                            "description": "A quick, clean ride with a sharp turn.",
                        }
                    ],
                }
            ],
        }
        log_text = "\n".join([
            "  🧹 Pre-QA skipped 1 subject-gated event(s) for surfer in dark swim trunks on a turquoise longboard",
            "  ⏭️  No clean single-athlete events for surfer in dark swim trunks on a turquoise longboard — no draft uploaded",
        ])
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        log_path.write_text(log_text, encoding="utf-8")

        audit = build_audit(ledger_path, trace_path, log_path)
        assert_true(audit["schema_version"] == "sportreel.selection_decision_audit.v1", "schema version missing")
        assert_true(audit["summary"]["candidate_count"] == 3, "candidate count must include selected and discarded")
        assert_true(audit["summary"]["selected_count"] == 1, "selected count should be retained")
        assert_true(audit["summary"]["discarded_count"] == 2, "discarded count should be retained")
        assert_true(audit["summary"]["selection_reason_coverage"] == "stage_and_reason_per_candidate", "coverage should be explicit")

        by_id = {row["candidate_id"]: row for row in audit["candidates"]}
        assert_true(by_id["discarded-480"]["discard_stage"] == "long_video_pre_qa_prefilter", "pre-QA log should identify subject-gated stage")
        assert_true(by_id["discarded-480"]["discard_cause_detailed"] == "subject_gated_by_pre_qa_prefilter", "subject-gated reason should be explicit")
        assert_true("pre_qa_prefilter" in by_id["discarded-480"]["evidence"], "pre-QA evidence lines should be preserved")
        assert_true(by_id["discarded-515"]["discard_cause_detailed"] == "shared_or_obstructed_window", "shared-wave descriptions should be classified")

        draft = audit["drafts"][0]
        assert_true(draft["selected_wave_count"] == 1, "draft should report one selected wave")
        assert_true(draft["related_unselected_candidate_count"] >= 1, "draft should show related unselected candidates")
        assert_true(draft["possible_identity_fragmentation_count"] >= 1, "similar same-board candidate should be flagged")

    pipeline_script = (ROOT / "scripts" / "run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "operator-smoke-check.yml").read_text(encoding="utf-8")
    for token in [
        "SELECTION_AUDIT_FILE",
        "build_selection_decision_audit.py",
        "selection_decision_audit.json",
        "append_selection_decision_audit_summary_to_report.py",
    ]:
        assert_true(token in pipeline_script, f"diagnostics runner missing {token}")
    assert_true("Validate Selection decision audit contract" in workflow, "workflow must run selection audit contract")

    print("selection decision audit contract ok")


if __name__ == "__main__":
    main()

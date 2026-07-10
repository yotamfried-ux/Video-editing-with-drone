#!/usr/bin/env python3
"""Contract for selection decision telemetry."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_module = _load(ROOT / "scripts" / "build_selection_decision_audit.py", "build_selection_decision_audit")
ledger_module = _load(ROOT / "scripts" / "build_candidate_decision_ledger.py", "build_candidate_decision_ledger")
build_audit = audit_module.build_audit
build_ledger = ledger_module.build_ledger


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ledger_path = tmp / "candidate_decision_ledger.json"
        trace_path = tmp / "draft_decision_trace.json"
        selector_path = tmp / "selector_candidate_events.json"
        filter_path = tmp / "selection_filter_events.json"
        log_path = tmp / "run_tracked.log"

        draft_name = "DRAFT_surfer in black shorts on a turquoise longboard_20260709.mp4"
        selector = {
            "schema_version": "sportreel.selector_candidate_events.v1",
            "candidates": [
                {
                    "candidate_id": "selected-459-upstream",
                    "person_id": "person_B",
                    "person_description": "surfer in black shorts on a turquoise longboard",
                    "selected": True,
                    "discarded": False,
                    "selection_reason": "score_above_threshold",
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
                    "selected": True,
                    "discarded": False,
                    "selection_reason": "score_above_threshold",
                    "event_type": "highlight",
                    "score": 9,
                    "source_video": "source.mp4",
                    "source_window": {"start": 480.0, "end": 491.0, "duration": 11.0},
                    "description": "Catches a wave and holds a long, clean line with smooth carves.",
                },
                {
                    "candidate_id": "discarded-515",
                    "person_id": "person_A",
                    "person_description": "surfer in pink swimsuit on a pink longboard",
                    "selected": True,
                    "discarded": False,
                    "selection_reason": "score_above_threshold",
                    "event_type": "wave_catch",
                    "score": 8,
                    "source_video": "source.mp4",
                    "source_window": {"start": 515.0, "end": 535.0, "duration": 20.0},
                    "description": "Shares a wave with another surfer while carving.",
                },
            ],
        }
        # Source video intentionally missing from trace: the ledger should still
        # merge this with the upstream selected candidate by physical window.
        trace = {
            "schema_version": "sportreel.draft_decision_trace.v1",
            "drafts": [
                {
                    "draft_id": draft_name,
                    "draft_name": draft_name,
                    "sport": "surfing",
                    "source_windows": [
                        {
                            "source_video": None,
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
        filter_trace = {
            "schema_version": "sportreel.selection_filter_events.v1",
            "records": [
                {
                    "source_video": "source.mp4",
                    "person_description": "surfer in black shorts on a turquoise longboard",
                    "event_type": "highlight",
                    "score": 7,
                    "source_window": {"start": 459.0, "end": 475.0, "duration": 16.0},
                    "description": "A quick, clean ride with a sharp turn.",
                    "selected_for_render": True,
                    "discarded": False,
                    "discard_stage": None,
                    "discard_cause": None,
                    "reason_codes": [],
                    "selection_rescue": {"attempted": True, "status": "clean_subwindow_rescued", "rescue_stage": "clean_subwindow_rescue"},
                },
                {
                    "source_video": "source.mp4",
                    "person_description": "surfer in dark swim trunks on a turquoise longboard",
                    "event_type": "highlight",
                    "score": 9,
                    "source_window": {"start": 480.0, "end": 491.0, "duration": 11.0},
                    "description": "Catches a wave and holds a long, clean line with smooth carves.",
                    "selected_for_render": False,
                    "discarded": True,
                    "discard_stage": "long_video_pre_qa_prefilter",
                    "discard_cause": "no_clean_subwindow_found",
                    "reason_codes": ["MULTI_PERSON_CLIP", "NO_CLEAN_SUBWINDOW_FOUND"],
                },
            ],
            "clean_subwindow_rescue_count": 1,
        }
        log_text = "\n".join([
            "  🧹 Pre-QA skipped 1 subject-gated event(s) for surfer in dark swim trunks on a turquoise longboard",
            "  ⏭️  No clean single-athlete events for surfer in dark swim trunks on a turquoise longboard — no draft uploaded",
        ])
        selector_path.write_text(json.dumps(selector), encoding="utf-8")
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        filter_path.write_text(json.dumps(filter_trace), encoding="utf-8")
        log_path.write_text(log_text, encoding="utf-8")

        ledger = build_ledger(trace_path, selector_path)
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        assert_true(ledger["selected_count"] == 1, "trace/upstream selected same window should merge into one selected row")
        assert_true(ledger["discarded_count"] == 2, "unemitted upstream candidates should remain discarded")
        assert_true(ledger["unmatched_selector_selected_count"] == 2, "only true non-draft candidates should be unmatched")

        audit = build_audit(ledger_path, trace_path, log_path, filter_path)
        assert_true(audit["schema_version"] == "sportreel.selection_decision_audit.v1", "schema version missing")
        assert_true(audit["summary"]["candidate_count"] == 3, "candidate count must include selected and discarded")
        assert_true(audit["summary"]["selected_count"] == 1, "selected count should be retained")
        assert_true(audit["summary"]["discarded_count"] == 2, "discarded count should be retained")
        assert_true(audit["summary"]["selection_filter_record_count"] == 2, "filter records should be counted")
        assert_true(audit["summary"]["event_level_reason_count"] >= 2, "event-level filter evidence should be attached")
        assert_true(audit["summary"]["selection_reason_coverage"] == "event_level_stage_and_reason_per_candidate", "coverage should be event-level")

        by_id = {row["candidate_id"]: row for row in audit["candidates"]}
        selected = by_id["selected-459-upstream"]
        assert_true(selected["selection_reason_detailed"] == "prefilter_passed_and_uploaded", "selected draft should show prefilter pass")
        assert_true(selected["decision_path"] == ["analyzer_selected", "prefilter_passed", "draft_uploaded"], "selected decision path should be explicit")
        assert_true(selected["evidence"]["selection_filter_event"]["selected_for_render"] is True, "selected filter evidence should be preserved")
        assert_true(selected["evidence"]["selection_filter_event"]["selection_rescue"]["status"] == "clean_subwindow_rescued", "rescued selected window should preserve rescue metadata")

        assert_true(by_id["discarded-480"]["discard_stage"] == "long_video_pre_qa_prefilter", "event trace should identify subject-gated stage")
        assert_true(by_id["discarded-480"]["discard_cause_detailed"] == "no_clean_subwindow_found", "no-clean-subwindow reason should be explicit")
        assert_true(by_id["discarded-480"]["decision_path"] == ["analyzer_selected", "prefilter_failed", "no_clean_subwindow_found"], "discarded decision path should be explicit")
        assert_true("selection_filter_event" in by_id["discarded-480"]["evidence"], "event-level prefilter evidence should be preserved")
        assert_true(by_id["discarded-515"]["discard_cause_detailed"] == "shared_or_obstructed_window", "shared-wave descriptions should be classified")

        draft = audit["drafts"][0]
        assert_true(draft["selected_wave_count"] == 1, "draft should report one selected wave")
        assert_true(draft["related_unselected_candidate_count"] >= 1, "draft should show related unselected candidates")
        assert_true(draft["possible_identity_fragmentation_count"] >= 1, "similar same-board candidate should be flagged")

    pipeline_script = (ROOT / "scripts" / "run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "operator-smoke-check.yml").read_text(encoding="utf-8")
    for token in [
        "SELECTION_FILTER_EVENTS_FILE",
        "selection_filter_events.json",
        "build_selection_decision_audit.py",
        "append_selection_decision_audit_summary_to_report.py",
    ]:
        assert_true(token in pipeline_script, f"diagnostics runner missing {token}")
    assert_true("Validate Selection decision audit contract" in workflow, "workflow must run selection audit contract")

    context_long = (ROOT / "pipeline" / "context_qa_long_video.py").read_text(encoding="utf-8")
    for token in [
        "_append_filter_trace",
        "_best_clean_subwindow",
        "clean_subwindow_rescued",
        "no_clean_subwindow_found",
        "NO_CLEAN_SUBWINDOW_FOUND",
        "MULTI_PERSON_CLIP",
        "sportreel.selection_filter_events.v1",
        "selected_for_render",
        "duplicate_source_window_before_render",
    ]:
        assert_true(token in context_long, f"context QA long-video missing event-level trace token {token}")

    run_tracked = (ROOT / "scripts" / "run_tracked.py").read_text(encoding="utf-8")
    for token in [
        "_no_reviewable_drafts_meta",
        "no_reviewable_drafts",
        "all_candidates_rejected_before_render",
        "selection_filter_events.json",
        "sys.exit(1)",
    ]:
        assert_true(token in run_tracked, f"run_tracked missing no-reviewable-drafts contract token {token}")

    print("selection decision audit contract ok")


if __name__ == "__main__":
    main()

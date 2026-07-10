#!/usr/bin/env python3
"""Regression contract for run 29111503822's PREMATURE_CUT QA bypass."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _minor_cut() -> dict:
    return {
        "type": "PREMATURE_CUT",
        "severity": "minor",
        "at_seconds": 7,
        "note": "ride ends before its natural completion",
    }


def _qa_fail() -> dict:
    return {
        "verdict": "FAIL",
        "defects": [_minor_cut()],
        "overall": "abrupt ending",
        "engagement_score": 68,
    }


def _fake_orchestrator(captured: dict) -> SimpleNamespace:
    from pipeline.stages import analyzer

    fake = SimpleNamespace()

    def original_apply(events, defects):
        captured["normalized_defects"] = defects
        return events, True

    def original_gate(reels, events_out, sport, athlete_label, recompile):
        events_by_reel = {reel: events for reel, events in events_out}
        flagged = set()
        for reel in reels:
            qa = analyzer.qa_check_reel(reel, sport=sport, athlete_label=athlete_label)
            if fake._qa_blocking(qa):
                flagged.add(reel)
        return list(reels), events_by_reel, flagged

    fake._qa_gate = original_gate
    fake._apply_qa_fixes = original_apply
    fake._save_reel_metadata = lambda *args, **kwargs: None
    return fake


def validate_policy() -> None:
    from pipeline import qa_gate_policy as policy

    minor_cut = _minor_cut()
    qa_fail = _qa_fail()
    require(policy.is_critical_defect(minor_cut), "minor PREMATURE_CUT must be product-blocking")
    require(policy.review_required_reason_codes(qa_fail) == ["PREMATURE_CUT"], "PREMATURE_CUT reason code missing")
    require(policy.approval_blocked_reasons(qa_fail)[0].startswith("PREMATURE_CUT:"), "approval block reason missing")
    require(policy.review_required_reason_codes({"verdict": "PASS", "defects": []}) == [], "clean QA must not get fallback review reasons")
    require(policy.approval_blocked_reasons({"verdict": "PASS", "defects": []}) == [], "clean QA must not get fallback approval blocks")
    print("premature-cut policy classification ok")


def validate_runtime_predicate() -> None:
    from pipeline import qa_gate_policy as policy

    captured: dict = {}
    fake = _fake_orchestrator(captured)
    policy._patch_orchestrator(fake)
    require(fake._qa_blocking(_qa_fail()), "patched orchestrator must block minor PREMATURE_CUT")
    fake._apply_qa_fixes([{"start": 0.0, "end": 8.0}], [_minor_cut()])
    require(captured["normalized_defects"][0]["severity"] == "critical", "PREMATURE_CUT must reach the existing repair path")
    print("premature-cut runtime predicate and repair routing ok")


def validate_runtime_final_block() -> None:
    import config
    from pipeline import qa_gate_policy as policy
    from pipeline.stages import analyzer

    qa_fail = _qa_fail()
    captured: dict = {}
    fake = _fake_orchestrator(captured)
    policy._patch_orchestrator(fake)

    original_check = analyzer.qa_check_reel
    original_enabled = config.QA_REEL_CHECK
    config.QA_REEL_CHECK = True
    analyzer.qa_check_reel = lambda *args, **kwargs: qa_fail
    try:
        final, events_by_reel, flagged = fake._qa_gate(
            ["reel.mp4"],
            [("reel.mp4", [{"start": 0.0, "end": 8.0, "type": "highlight"}])],
            "surfing",
            "surfer on turquoise longboard",
            lambda events, out: [],
        )
    finally:
        analyzer.qa_check_reel = original_check
        config.QA_REEL_CHECK = original_enabled

    require(final == ["reel.mp4"], "fake gate should retain final reel")
    require("reel.mp4" in flagged, "PREMATURE_CUT final must be review-blocked")
    gate = events_by_reel["reel.mp4"][0]["qa_gate"]
    require(gate["decision"] == "blocked_review_required", "final blocking decision missing")
    require(gate["qa_review_required"] is True, "review-required flag missing")
    require(gate["critical_defect_count"] == 1, "blocking defect count wrong")
    require(gate["defects"][0]["blocking"] is True, "defect must be marked blocking")
    print("premature-cut final block diagnostics ok")


def validate_runtime_nonblocking() -> None:
    import config
    from pipeline import qa_gate_policy as policy
    from pipeline.stages import analyzer

    nonblocking_qa = {
        "verdict": "FAIL",
        "defects": [],
        "overall": "no audio track",
        "engagement_score": 65,
    }
    captured: dict = {}
    fake = _fake_orchestrator(captured)
    policy._patch_orchestrator(fake)

    original_check = analyzer.qa_check_reel
    original_enabled = config.QA_REEL_CHECK
    analyzer.qa_check_reel = lambda *args, **kwargs: nonblocking_qa
    config.QA_REEL_CHECK = True
    try:
        _final, events_by_reel, flagged = fake._qa_gate(
            ["reel2.mp4"],
            [("reel2.mp4", [{"start": 0.0, "end": 10.0, "type": "highlight"}])],
            "surfing",
            "surfer",
            lambda events, out: [],
        )
    finally:
        analyzer.qa_check_reel = original_check
        config.QA_REEL_CHECK = original_enabled

    gate = events_by_reel["reel2.mp4"][0]["qa_gate"]
    require(not flagged, "technical-only FAIL must not create a content re-edit block")
    require(gate["decision"] == "failed_nonblocking", "nonblocking final decision missing")
    require(gate["approval_blocked_reasons"] == [], "nonblocking final must not block approval")
    print("final nonblocking QA telemetry ok")


def validate_log_summary() -> None:
    from scripts.append_qa_gate_summary_to_report import _qa_summary

    log = "\n".join([
        "🟡 PREMATURE_CUT @7s — abrupt ending",
        "🚩 QA still failing after 2 re-edit(s) — uploading FLAGGED for operator review",
        "DRAFT_surfer QA-FLAGGED",
        "✅ 1 draft(s) uploaded to REVIEW folder",
    ])
    raw = _qa_summary(log, {"metrics": {"draft_count": 1}})
    require(raw["qa_flagged_draft_count"] == 1, "flagged draft must not be double-counted")
    require(raw["unflagged_uploaded_draft_count"] == 0, "flagged upload must not count as unflagged bypass")
    require(raw["qa_gate_bypass_rate"] == 0.0, "explicit flagged upload is not a gate bypass")
    print("QA log classification ok")


def validate_final_trace() -> None:
    from scripts.append_qa_policy_trace_summary_to_report import append_summary

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        report_path = root / "report.json"
        trace_path = root / "trace.json"
        report_path.write_text(json.dumps({
            "status": "fail",
            "metrics": {"uploaded_draft_count": 2, "qa_gate_bypass_rate": 1.0},
            "alerts": [
                {"metric": "qa_critical_defect_count", "severity": "hard_block"},
                {"metric": "qa_gate_bypass_rate", "severity": "hard_block"},
            ],
            "bug_classifications": [{"code": "BUG_QA_GATE_BYPASSED"}],
            "qa_gate_summary": {"qa_gate_bypass_rate": 1.0},
            "implementation_gaps": {},
        }), encoding="utf-8")
        trace_path.write_text(json.dumps({
            "drafts": [
                {
                    "draft_id": "repaired",
                    "draft_name": "DRAFT_repaired.mp4",
                    "qa_gate": {
                        "decision": "passed_after_reedit",
                        "retry_count": 1,
                        "qa_review_required": False,
                        "review_required_reasons": [],
                        "approval_blocked_reasons": [],
                        "defects": [],
                    },
                },
                {
                    "draft_id": "blocked",
                    "draft_name": "DRAFT_blocked QA-FLAGGED.mp4",
                    "qa_status": "review_required",
                    "review_required_reasons": ["PREMATURE_CUT"],
                    "approval_blocked_reasons": ["PREMATURE_CUT: still abrupt"],
                    "qa_gate": {
                        "decision": "blocked_review_required",
                        "retry_count": 2,
                        "qa_review_required": True,
                        "defects": [{
                            "type": "PREMATURE_CUT",
                            "severity": "minor",
                            "blocking": True,
                        }],
                    },
                },
            ]
        }), encoding="utf-8")
        report = append_summary(report_path, trace_path)

    metrics = report["metrics"]
    require(report["status"] == "pass", "explicit repaired/blocked finals should clear transient log failure")
    require(metrics["qa_gate_bypass_rate"] == 0.0, "final QA trace must clear false bypass")
    require(metrics["qa_final_explicit_draft_count"] == 2, "all final drafts should be explicit")
    require(metrics["qa_blocked_draft_count"] == 1, "one final draft should remain blocked")
    require(metrics["qa_unblocked_final_draft_count"] == 1, "one repaired final draft should be unblocked")
    require(metrics["qa_retry_count_total"] == 3, "retry telemetry should be aggregated")
    print("final QA trace reconciliation ok")


def validate_workflow() -> None:
    workflow = (ROOT / ".github" / "workflows" / "operator-smoke-check.yml").read_text(encoding="utf-8")
    required_steps = [
        "Validate Premature-cut policy classification",
        "Validate Premature-cut runtime predicate",
        "Validate Premature-cut final block diagnostics",
        "Validate Final nonblocking QA telemetry",
        "Validate QA flagged-upload classification",
        "Validate Final QA trace reconciliation",
    ]
    for step in required_steps:
        require(step in workflow, f"Operator Smoke missing step: {step}")
    require("test_premature_cut_qa_gate_contract.py" in workflow, "workflow path trigger missing")
    print("premature-cut workflow wiring ok")


VALIDATORS = {
    "policy": validate_policy,
    "runtime-predicate": validate_runtime_predicate,
    "runtime-final-block": validate_runtime_final_block,
    "runtime-nonblocking": validate_runtime_nonblocking,
    "log-summary": validate_log_summary,
    "final-trace": validate_final_trace,
    "workflow": validate_workflow,
}


def main() -> int:
    modes = sys.argv[1:] or list(VALIDATORS)
    unknown = [mode for mode in modes if mode not in VALIDATORS]
    if unknown:
        raise SystemExit(f"unknown validation mode(s): {unknown}; choose from {sorted(VALIDATORS)}")
    for mode in modes:
        VALIDATORS[mode]()
    print("premature-cut QA gate contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

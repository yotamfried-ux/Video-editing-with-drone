#!/usr/bin/env python3
"""Regression contract for run 29111503822's PREMATURE_CUT QA bypass."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

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

    require(policy.qa_blocking_with_policy(_qa_fail()), "runtime policy must block minor PREMATURE_CUT")
    require(not policy.qa_blocking_with_policy({"verdict": "PASS", "defects": [_minor_cut()]}), "PASS verdict must not be blocked")
    print("premature-cut runtime predicate ok")


def validate_repair_routing() -> None:
    from pipeline import qa_gate_policy as policy

    source = _minor_cut()
    normalized = policy.normalize_defects_for_repair([source])
    require(normalized[0]["severity"] == "critical", "PREMATURE_CUT must reach the existing repair path as critical")
    require(source["severity"] == "minor", "repair normalization must not mutate source QA payload")
    print("premature-cut repair routing ok")


def validate_runtime_final_block() -> None:
    from pipeline import qa_gate_policy as policy

    diagnostics, should_review_block = policy.build_final_qa_diagnostics(
        _qa_fail(),
        retry_count=2,
        reel_path="reel.mp4",
        was_flagged=False,
    )
    require(should_review_block, "PREMATURE_CUT final must be review-blocked")
    require(diagnostics["decision"] == "blocked_review_required", "final blocking decision missing")
    require(diagnostics["qa_review_required"] is True, "review-required flag missing")
    require(diagnostics["critical_defect_count"] == 1, "blocking defect count wrong")
    require(diagnostics["defects"][0]["blocking"] is True, "defect must be marked blocking")
    require(diagnostics["review_required_reasons"] == ["PREMATURE_CUT"], "review reason missing")
    require(diagnostics["retry_count"] == 2, "retry count missing from final diagnostics")
    print("premature-cut final block diagnostics ok")


def validate_visual_family() -> None:
    from pipeline import qa_gate_policy as policy

    clean = "/tmp/REEL_wave.mp4"
    music = "/tmp/REEL_wave_music.mp4"
    other = "/tmp/REEL_other.mp4"
    final_reels = [clean, music, other]
    events_by_reel = {
        clean: [{"event_id": "clean", "start": 0.0, "end": 8.0}],
        music: [{"event_id": "music", "start": 0.0, "end": 8.0}],
        other: [{"event_id": "other", "start": 20.0, "end": 30.0}],
    }
    flagged: set[str] = set()

    diagnostics, blocked = policy.apply_final_qa_to_visual_family(
        final_reels,
        events_by_reel,
        flagged,
        clean,
        _qa_fail(),
        retry_count=2,
    )
    require(blocked, "blocking clean reel must block its visual family")
    require(clean in flagged, "clean reel must be flagged")
    require(music in flagged, "music sibling with identical visuals must be flagged")
    require(other not in flagged, "unrelated reel must not inherit the QA block")
    require(events_by_reel[clean][0]["qa_gate"]["decision"] == "blocked_review_required", "clean diagnostics missing")
    require(events_by_reel[music][0]["qa_gate"]["decision"] == "blocked_review_required", "music sibling diagnostics missing")
    require(events_by_reel[music][0]["event_id"] == "music", "music sibling events must be preserved")
    require(diagnostics["retry_count"] == 2, "family diagnostics must preserve per-reel retry count")

    counts = {
        policy.visual_family_key(clean): 3,
        policy.visual_family_key(other): 1,
    }
    require(policy.visual_family_key(clean) == policy.visual_family_key(music), "clean/music siblings must share a visual family key")
    require(policy.retry_count_for_reel(counts, clean) == 2, "clean reel retry count should be local to its family")
    require(policy.retry_count_for_reel(counts, music) == 2, "music sibling should inherit its visual family's retry count")
    require(policy.retry_count_for_reel(counts, other) == 0, "one reel's retries must not contaminate another reel")
    print("visual-family QA propagation and per-reel retry accounting ok")


def validate_runtime_nonblocking() -> None:
    from pipeline import qa_gate_policy as policy

    nonblocking_qa = {
        "verdict": "FAIL",
        "defects": [],
        "overall": "no audio track",
        "engagement_score": 65,
    }
    diagnostics, should_review_block = policy.build_final_qa_diagnostics(
        nonblocking_qa,
        retry_count=0,
        reel_path="reel2.mp4",
        was_flagged=False,
    )
    require(not should_review_block, "technical-only FAIL must not create a content re-edit block")
    require(diagnostics["decision"] == "failed_nonblocking", "nonblocking final decision missing")
    require(diagnostics["approval_blocked_reasons"] == [], "nonblocking final must not block approval")
    print("final nonblocking QA telemetry ok")


def validate_trace_precedence() -> None:
    from scripts.build_draft_decision_trace import _qa_status

    failed_nonblocking = {
        "decision": "failed_nonblocking",
        "final_verdict": "FAIL",
        "qa_review_required": False,
        "review_required_reasons": [],
        "approval_blocked_reasons": [],
        "defects": [],
    }
    status, reasons = _qa_status("DRAFT_clean.mp4", {}, failed_nonblocking)
    require(status == "not_required", "failed_nonblocking must not be converted back to review_required")
    require(reasons == [], "failed_nonblocking must not emit review reasons")

    blocked = {
        "decision": "blocked_review_required",
        "final_verdict": "FAIL",
        "qa_review_required": True,
        "review_required_reasons": ["PREMATURE_CUT"],
        "defects": [{"type": "PREMATURE_CUT", "severity": "minor", "blocking": True}],
    }
    status, reasons = _qa_status("DRAFT_blocked.mp4", {}, blocked)
    require(status == "review_required", "explicit blocked decision must remain review_required")
    require(reasons == ["PREMATURE_CUT"], "explicit blocked reason must be retained")
    print("draft trace final-decision precedence ok")


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
    policy_source = (ROOT / "pipeline" / "qa_gate_policy.py").read_text(encoding="utf-8")
    trace_source = (ROOT / "scripts" / "build_draft_decision_trace.py").read_text(encoding="utf-8")
    required_steps = [
        "Validate Premature-cut policy classification",
        "Validate Premature-cut runtime predicate",
        "Validate Premature-cut repair routing",
        "Validate Premature-cut final block diagnostics",
        "Validate Visual-family QA propagation",
        "Validate Final nonblocking QA telemetry",
        "Validate Draft trace decision precedence",
        "Validate QA flagged-upload classification",
        "Validate Final QA trace reconciliation",
    ]
    for step in required_steps:
        require(step in workflow, f"Operator Smoke missing step: {step}")
    require("test_premature_cut_qa_gate_contract.py" in workflow, "workflow path trigger missing")
    require("orchestrator._qa_blocking = qa_blocking_with_policy" in policy_source, "runtime block helper is not wired")
    require("normalize_defects_for_repair(defects)" in policy_source, "repair helper is not wired")
    require("apply_final_qa_to_visual_family(" in policy_source, "visual-family final QA helper is not wired")
    require("retry_count_for_reel(qa_call_counts, reel)" in policy_source, "per-reel retry helper is not wired")
    require("decision in _NONBLOCKING_FINAL_DECISIONS" in trace_source, "draft trace does not honor nonblocking final decisions")
    print("premature-cut workflow wiring ok")


VALIDATORS = {
    "policy": validate_policy,
    "runtime-predicate": validate_runtime_predicate,
    "repair-routing": validate_repair_routing,
    "runtime-final-block": validate_runtime_final_block,
    "visual-family": validate_visual_family,
    "runtime-nonblocking": validate_runtime_nonblocking,
    "trace-precedence": validate_trace_precedence,
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

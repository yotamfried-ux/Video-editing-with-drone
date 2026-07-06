#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

CRITICAL_DEFECTS = {
    "IDENTITY_MISMATCH",
    "DUPLICATE_MOMENT",
    "PREMATURE_CUT",
    "MULTI_PERSON_CLIP",
    "MISSING_SOURCE_EVIDENCE",
    "CUT_TOO_EARLY",
}
KNOWN_DEFECTS = CRITICAL_DEFECTS | {
    "DEAD_TIME",
    "NO_VISIBLE_ACTION",
    "BAD_FIRST_CLIP",
    "BAD_CROP",
    "LOW_ACTION_DENSITY",
}
DEFECT_PATTERN = re.compile(r"\b(" + "|".join(sorted(KNOWN_DEFECTS)) + r")\b")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _log_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _qa_summary(log: str, report: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(DEFECT_PATTERN.findall(log))
    critical_counts = {name: counts[name] for name in sorted(CRITICAL_DEFECTS) if counts[name]}
    defect_counts = {name: counts[name] for name in sorted(counts)}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    draft_count = int(metrics.get("draft_count") or 0)
    trace = report.get("draft_decision_trace") if isinstance(report.get("draft_decision_trace"), dict) else {}
    qa_flagged_from_trace = 0
    # Current trace summary does not include draft names, so also use log/name markers.
    qa_flagged_from_log = log.count("QA-FLAGGED")
    qa_still_failing = log.count("QA still failing")
    no_actionable_fix = log.count("No actionable fix for QA defects")
    critical_total = sum(critical_counts.values())
    bypass = critical_total > 0 and draft_count > 0
    return {
        "qa_defect_counts": defect_counts,
        "qa_critical_defect_counts": critical_counts,
        "qa_defect_count": sum(defect_counts.values()),
        "qa_critical_defect_count": critical_total,
        "qa_flagged_draft_count": qa_flagged_from_trace + qa_flagged_from_log,
        "qa_still_failing_count": qa_still_failing,
        "qa_no_actionable_fix_count": no_actionable_fix,
        "qa_gate_bypass_rate": 1.0 if bypass else 0.0,
        "qa_policy_explicit": False,
    }


def append_summary(report_path: Path, log_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    log = _log_text(log_path)
    summary = _qa_summary(log, report)
    metrics = report.setdefault("metrics", {})
    metrics.update({
        "qa_defect_count": summary["qa_defect_count"],
        "qa_critical_defect_count": summary["qa_critical_defect_count"],
        "qa_flagged_draft_count": summary["qa_flagged_draft_count"],
        "qa_still_failing_count": summary["qa_still_failing_count"],
        "qa_no_actionable_fix_count": summary["qa_no_actionable_fix_count"],
        "qa_gate_bypass_rate": summary["qa_gate_bypass_rate"],
    })
    report["qa_gate_summary"] = summary
    alerts = report.setdefault("alerts", [])
    classifications = report.setdefault("bug_classifications", [])
    if summary["qa_critical_defect_count"] > 0:
        alerts.append({
            "metric": "qa_critical_defect_count",
            "severity": "hard_block",
            "reason": "critical QA defects were present in the run log",
        })
    if summary["qa_gate_bypass_rate"] > 0:
        alerts.append({
            "metric": "qa_gate_bypass_rate",
            "severity": "hard_block",
            "reason": "critical QA defects existed while drafts were still produced",
        })
        classifications.append({
            "code": "BUG_QA_GATE_BYPASSED",
            "evidence": f"critical_qa_defects={summary['qa_critical_defect_count']} draft_count={metrics.get('draft_count', 0)}",
        })
    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["qa_gate_policy_metric_ready"] = True
        gaps["qa_gate_policy_explicit"] = summary["qa_policy_explicit"]
    if any(alert.get("severity") == "hard_block" for alert in alerts if isinstance(alert, dict)):
        report["status"] = "fail"
    elif report.get("status") not in {"fail", "pass", "inconclusive", "regressed"}:
        report["status"] = "inconclusive"
    _write_json(report_path, report)
    return report


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_qa_gate_summary_to_report.py RUN_QUALITY_REPORT_JSON RUN_LOG", file=sys.stderr)
        return 2
    report = append_summary(Path(sys.argv[1]), Path(sys.argv[2]))
    qa = report.get("qa_gate_summary", {})
    print(
        "qa gate summary "
        f"critical={qa.get('qa_critical_defect_count', 0)} "
        f"bypass_rate={qa.get('qa_gate_bypass_rate', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

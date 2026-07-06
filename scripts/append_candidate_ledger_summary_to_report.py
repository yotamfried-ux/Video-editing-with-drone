#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _summary(ledger: dict[str, Any]) -> dict[str, Any]:
    candidates = [item for item in ledger.get("candidates", []) if isinstance(item, dict)]
    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded = [item for item in candidates if item.get("discarded")]
    discarded_with_cause = [item for item in discarded if item.get("discard_cause")]
    unmatched_selector_selected_count = sum(1 for item in candidates if item.get("unmatched_selector_selection"))
    return {
        "schema_version": ledger.get("schema_version"),
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": len(discarded),
        "unmatched_selector_selected_count": unmatched_selector_selected_count,
        "discard_cause_coverage_rate": (len(discarded_with_cause) / len(discarded)) if discarded else 0.0,
        "recall_status": ledger.get("recall_status") or "missing",
        "known_gap": ledger.get("known_gap"),
    }


def _recall_is_measurable(summary: dict[str, Any]) -> bool:
    return summary["selected_count"] > 0 and summary["discarded_count"] > 0 and summary["discard_cause_coverage_rate"] == 1.0


def _remove_recall_unknown(report: dict[str, Any]) -> None:
    report["bug_classifications"] = [
        item for item in report.get("bug_classifications", [])
        if not (isinstance(item, dict) and item.get("code") == "BUG_RECALL_UNKNOWN")
    ]
    report["alerts"] = [
        item for item in report.get("alerts", [])
        if not (isinstance(item, dict) and item.get("metric") in {"missing_dropped_reasons", "candidate_discarded_count"})
    ]


def append_summary(report_path: Path, ledger_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    ledger = _read_json(ledger_path)
    summary = _summary(ledger)
    metrics = report.setdefault("metrics", {})
    metrics.update({
        "candidate_ledger_count": summary["candidate_count"],
        "candidate_selected_count": summary["selected_count"],
        "candidate_discarded_count": summary["discarded_count"],
        "candidate_unmatched_selector_selected_count": summary["unmatched_selector_selected_count"],
        "candidate_discard_cause_coverage_rate": summary["discard_cause_coverage_rate"],
    })
    report["candidate_decision_ledger"] = summary
    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["candidate_decision_ledger_present"] = bool(ledger)
        gaps["candidate_discarded_causes_present"] = _recall_is_measurable(summary)
        gaps["unmatched_selector_selection_metric_ready"] = True
    alerts = report.setdefault("alerts", [])
    classifications = report.setdefault("bug_classifications", [])
    if summary["candidate_count"] == 0:
        alerts.append({
            "metric": "candidate_ledger_count",
            "severity": "inconclusive",
            "reason": "candidate decision ledger is empty or missing",
        })
    if _recall_is_measurable(summary):
        _remove_recall_unknown(report)
    elif summary["selected_count"] > 0 and summary["discarded_count"] == 0:
        alerts.append({
            "metric": "candidate_discarded_count",
            "severity": "inconclusive",
            "reason": "ledger contains selected candidates but no discarded candidates, so recall cannot be proven",
        })
        if not any(item.get("code") == "BUG_RECALL_UNKNOWN" for item in classifications if isinstance(item, dict)):
            classifications.append({
                "code": "BUG_RECALL_UNKNOWN",
                "evidence": "candidate ledger is selected_only; discarded candidates are not emitted yet",
            })
    if report.get("status") == "pass" and any(alert.get("severity") == "inconclusive" for alert in alerts if isinstance(alert, dict)):
        report["status"] = "inconclusive"
    _write_json(report_path, report)
    return report


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_candidate_ledger_summary_to_report.py RUN_QUALITY_REPORT_JSON CANDIDATE_LEDGER_JSON", file=sys.stderr)
        return 2
    report = append_summary(Path(sys.argv[1]), Path(sys.argv[2]))
    summary = report.get("candidate_decision_ledger", {})
    print(
        "candidate ledger summary "
        f"candidates={summary.get('candidate_count', 0)} "
        f"selected={summary.get('selected_count', 0)} "
        f"discarded={summary.get('discarded_count', 0)} "
        f"unmatched_selector_selected={summary.get('unmatched_selector_selected_count', 0)} "
        f"recall_status={summary.get('recall_status', 'missing')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

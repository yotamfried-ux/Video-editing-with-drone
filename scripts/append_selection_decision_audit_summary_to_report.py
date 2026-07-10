#!/usr/bin/env python3
"""Append selection-decision audit metrics to run_quality_report.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".selection-audit.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_selection_decision_audit_summary_to_report.py RUN_QUALITY_REPORT_JSON SELECTION_DECISION_AUDIT_JSON", file=sys.stderr)
        return 2
    report_path = Path(sys.argv[1])
    audit_path = Path(sys.argv[2])
    report = _read(report_path)
    audit = _read(audit_path)
    if not report or not audit:
        return 0
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    report["selection_audit_status"] = "present"
    report["selection_audit_schema_version"] = audit.get("schema_version")
    report["selection_audit_candidate_count"] = summary.get("candidate_count", 0)
    report["selection_audit_selected_count"] = summary.get("selected_count", 0)
    report["selection_audit_discarded_count"] = summary.get("discarded_count", 0)
    report["selection_audit_discard_stage_counts"] = summary.get("discard_stage_counts", {})
    report["selection_audit_discard_cause_counts"] = summary.get("discard_cause_counts", {})
    report["selection_audit_possible_identity_fragmentation_count"] = summary.get("possible_identity_fragmentation_count", 0)
    report["selection_reason_coverage"] = summary.get("selection_reason_coverage")
    _write(report_path, report)
    print("selection audit summary appended")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

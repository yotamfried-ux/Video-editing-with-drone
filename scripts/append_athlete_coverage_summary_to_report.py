#!/usr/bin/env python3
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
    tmp = path.with_suffix(path.suffix + ".athlete-coverage.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_athlete_coverage_summary_to_report.py RUN_QUALITY_REPORT_JSON ATHLETE_COVERAGE_REPORT_JSON", file=sys.stderr)
        return 2
    report_path = Path(sys.argv[1])
    coverage_path = Path(sys.argv[2])
    report = _read(report_path)
    coverage = _read(coverage_path)
    if not report or not coverage:
        return 0
    summary = coverage.get("summary") if isinstance(coverage.get("summary"), dict) else {}
    metrics = report.setdefault("metrics", {})
    for key in (
        "confirmed_athlete_cluster_count",
        "represented_athlete_cluster_count",
        "covered_or_explicitly_explained_cluster_count",
        "athlete_draft_coverage_rate",
        "athlete_accountability_rate",
        "candidate_action_count",
        "selected_action_count",
        "selected_identity_lineage_complete_count",
        "selected_identity_lineage_completeness_rate",
        "candidate_action_seconds",
        "selected_action_seconds",
        "action_source_utilization_rate",
        "coverage_gap_cluster_count",
    ):
        metrics[key] = summary.get(key, 0)
    report["athlete_coverage_status"] = "present"
    report["athlete_coverage_schema_version"] = coverage.get("schema_version")
    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["athlete_coverage_metric_ready"] = True
        gaps["athlete_coverage_complete"] = summary.get("coverage_gap_cluster_count", 0) == 0
        gaps["selected_identity_lineage_complete"] = summary.get("selected_identity_lineage_completeness_rate", 0) == 1.0
    _write(report_path, report)
    print(
        "athlete coverage summary appended "
        f"coverage={summary.get('athlete_draft_coverage_rate', 0)} "
        f"accountability={summary.get('athlete_accountability_rate', 0)} "
        f"lineage={summary.get('selected_identity_lineage_completeness_rate', 0)} "
        f"utilization={summary.get('action_source_utilization_rate', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

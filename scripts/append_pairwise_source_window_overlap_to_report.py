#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

OVERLAP_MIN_SECONDS = 2.0
OVERLAP_MIN_RATIO = 0.5


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _source_name(value: Any) -> str:
    return Path(str(value)).name if value is not None else ""


def _sources_match(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left) == str(right) or _source_name(left) == _source_name(right)


def _valid_window(window: Any, fallback_source: Any = None) -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    start = window.get("start")
    end = window.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if end <= start:
        return None
    source_video = window.get("source_video") or fallback_source
    if not source_video:
        return None
    return {
        "source_video": str(source_video),
        "start": float(start),
        "end": float(end),
        "duration": float(end) - float(start),
    }


def source_window_records(trace: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for draft in trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        draft_id = draft.get("draft_id") or draft.get("draft_name")
        draft_name = draft.get("draft_name") or draft.get("draft_id")
        aggregate = draft.get("source_window") if isinstance(draft.get("source_window"), dict) else {}
        fallback_source = aggregate.get("source_video") if isinstance(aggregate, dict) else None
        windows = [w for w in draft.get("source_windows", []) if isinstance(w, dict)]
        if not windows and isinstance(aggregate, dict):
            windows = [aggregate]
        for idx, window in enumerate(windows):
            record = _valid_window(window, fallback_source)
            if not record:
                continue
            records.append({
                "draft_id": draft_id,
                "draft_name": draft_name,
                "source_window_index": idx,
                **record,
            })
    return records


def possible_pair_count(records: list[dict[str, Any]]) -> int:
    count = 0
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            if left.get("draft_id") == right.get("draft_id"):
                continue
            if _sources_match(left.get("source_video"), right.get("source_video")):
                count += 1
    return count


def pairwise_duplicates(trace: dict[str, Any]) -> list[dict[str, Any]]:
    records = source_window_records(trace)
    duplicates: list[dict[str, Any]] = []
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            if left.get("draft_id") == right.get("draft_id"):
                continue
            if not _sources_match(left.get("source_video"), right.get("source_video")):
                continue
            overlap = min(left["end"], right["end"]) - max(left["start"], right["start"])
            if overlap <= 0:
                continue
            shorter = min(left["duration"], right["duration"])
            ratio = _safe_div(overlap, shorter)
            if overlap >= OVERLAP_MIN_SECONDS and ratio >= OVERLAP_MIN_RATIO:
                duplicates.append({
                    "left_draft": left["draft_name"],
                    "right_draft": right["draft_name"],
                    "source_video": left["source_video"],
                    "left_window": {"index": left["source_window_index"], "start": left["start"], "end": left["end"]},
                    "right_window": {"index": right["source_window_index"], "start": right["start"], "end": right["end"]},
                    "overlap_seconds": round(overlap, 3),
                    "overlap_ratio_of_shorter": round(ratio, 3),
                })
    return duplicates


def append_summary(report_path: Path, trace_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    trace = _read_json(trace_path)
    records = source_window_records(trace)
    duplicates = pairwise_duplicates(trace)
    possible_pairs = possible_pair_count(records)
    metrics = report.setdefault("metrics", {})
    metrics["source_window_overlap_pair_count"] = len(duplicates)
    metrics["source_window_overlap_possible_pair_count"] = possible_pairs
    metrics["source_window_overlap_duplicate_rate"] = _safe_div(len(duplicates), possible_pairs)
    report["source_window_overlap_duplicates"] = duplicates
    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["source_window_overlap_pairwise_metric_ready"] = True
        gaps["source_window_overlap_aggregate_metric_deprecated"] = True
    report["alerts"] = [
        item for item in report.get("alerts", [])
        if not (isinstance(item, dict) and item.get("metric") == "source_window_overlap_duplicate_rate")
    ]
    report["bug_classifications"] = [
        item for item in report.get("bug_classifications", [])
        if not (isinstance(item, dict) and item.get("code") == "BUG_DUPLICATE_MOMENT_LIKELY")
    ]
    if duplicates:
        report.setdefault("alerts", []).append({
            "metric": "source_window_overlap_duplicate_rate",
            "severity": "hard_block",
            "reason": "two or more drafts strongly overlap the same concrete source window",
        })
        report.setdefault("bug_classifications", []).append({
            "code": "BUG_DUPLICATE_MOMENT_LIKELY",
            "evidence": f"{len(duplicates)} overlapping concrete source-window pair(s)",
        })
    if any(isinstance(item, dict) and item.get("severity") == "hard_block" for item in report.get("alerts", [])):
        report["status"] = "fail"
    elif any(isinstance(item, dict) and item.get("severity") == "inconclusive" for item in report.get("alerts", [])):
        report["status"] = "inconclusive"
    else:
        report["status"] = "pass"
    _write_json(report_path, report)
    return report


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_pairwise_source_window_overlap_to_report.py RUN_QUALITY_REPORT_JSON DRAFT_DECISION_TRACE_JSON", file=sys.stderr)
        return 2
    report = append_summary(Path(sys.argv[1]), Path(sys.argv[2]))
    metrics = report.get("metrics", {})
    print(
        "pairwise source-window overlap "
        f"duplicates={metrics.get('source_window_overlap_pair_count', 0)} "
        f"possible={metrics.get('source_window_overlap_possible_pair_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    return 0.0 if denominator <= 0 else numerator / denominator


def _valid_window(window: Any) -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    start = window.get("start")
    end = window.get("end")
    source_video = window.get("source_video")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if not source_video or end <= start:
        return None
    return {"source_video": str(source_video), "start": float(start), "end": float(end)}


def _window_records(trace: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for draft in trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        draft_id = draft.get("draft_id") or draft.get("draft_name")
        draft_name = draft.get("draft_name") or draft_id
        windows = [item for item in draft.get("source_windows", []) or [] if _valid_window(item)]
        source = "source_windows"
        if not windows:
            aggregate = _valid_window(draft.get("source_window"))
            windows = [aggregate] if aggregate else []
            source = "source_window"
        for index, window in enumerate(windows):
            if not window:
                continue
            records.append({
                "draft_id": draft_id,
                "draft_name": draft_name,
                "window_index": index,
                "window_source": source,
                "source_video": window["source_video"],
                "start": window["start"],
                "end": window["end"],
                "duration": window["end"] - window["start"],
            })
    return records


def pairwise_source_window_overlaps(trace: dict[str, Any]) -> list[dict[str, Any]]:
    records = _window_records(trace)
    duplicates: list[dict[str, Any]] = []
    seen_draft_pairs: set[tuple[str, str]] = set()
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            if left["draft_id"] == right["draft_id"]:
                continue
            if left["source_video"] != right["source_video"]:
                continue
            overlap = min(left["end"], right["end"]) - max(left["start"], right["start"])
            if overlap <= 0:
                continue
            shorter = min(left["duration"], right["duration"])
            ratio = _safe_div(overlap, shorter)
            if overlap < OVERLAP_MIN_SECONDS or ratio < OVERLAP_MIN_RATIO:
                continue
            pair_key = tuple(sorted([str(left["draft_id"]), str(right["draft_id"])]))
            if pair_key in seen_draft_pairs:
                continue
            seen_draft_pairs.add(pair_key)
            duplicates.append({
                "left_draft": left["draft_name"],
                "right_draft": right["draft_name"],
                "source_video": left["source_video"],
                "left_window": {"start": left["start"], "end": left["end"], "index": left["window_index"], "source": left["window_source"]},
                "right_window": {"start": right["start"], "end": right["end"], "index": right["window_index"], "source": right["window_source"]},
                "overlap_seconds": round(overlap, 3),
                "overlap_ratio_of_shorter": round(ratio, 3),
            })
    return duplicates


def append_summary(report_path: Path, trace_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    trace = _read_json(trace_path)
    metrics = report.setdefault("metrics", {})
    draft_count = int(metrics.get("draft_count") or len(trace.get("drafts", []) or []))
    possible_pairs = draft_count * (draft_count - 1) / 2
    previous_duplicates = report.get("source_window_overlap_duplicates", [])
    previous_count = len(previous_duplicates) if isinstance(previous_duplicates, list) else 0
    duplicates = pairwise_source_window_overlaps(trace)

    metrics["source_window_overlap_aggregate_pair_count"] = previous_count
    metrics["source_window_overlap_pair_count"] = len(duplicates)
    metrics["source_window_overlap_duplicate_rate"] = _safe_div(len(duplicates), possible_pairs)
    metrics["source_window_overlap_pairwise_ready"] = True
    report["source_window_overlap_duplicates"] = duplicates

    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["source_window_overlap_pairwise_ready"] = True

    if not duplicates:
        report["alerts"] = [
            item for item in report.get("alerts", [])
            if not (isinstance(item, dict) and item.get("metric") == "source_window_overlap_duplicate_rate")
        ]
        report["bug_classifications"] = [
            item for item in report.get("bug_classifications", [])
            if not (isinstance(item, dict) and item.get("code") == "BUG_DUPLICATE_MOMENT_LIKELY")
        ]
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
        f"pairs={metrics.get('source_window_overlap_pair_count', 0)} "
        f"aggregate_pairs={metrics.get('source_window_overlap_aggregate_pair_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

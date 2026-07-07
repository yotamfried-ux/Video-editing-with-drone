#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

MIN_DETECTIONS = 4
MIN_VISIBLE_TRACKS = 2
MAX_PRIMARY_DOMINANCE = 0.70


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
    return bool(left and right and (str(left) == str(right) or _source_name(left) == _source_name(right)))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _window_from_event(window: dict[str, Any], fallback_source: Any) -> dict[str, Any] | None:
    start = window.get("final_cut_start", window.get("start"))
    end = window.get("final_cut_end", window.get("end"))
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    start = float(start)
    end = float(end)
    if end <= start:
        return None
    if end - start > 11.0:
        start = round(end - 11.0, 2)
    source = window.get("source_video") or fallback_source
    if not source:
        return None
    return {"source_video": str(source), "start": start, "end": end, "duration": end - start}


def _records(trace: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for draft in trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        aggregate = draft.get("source_window") if isinstance(draft.get("source_window"), dict) else {}
        fallback_source = aggregate.get("source_video") if isinstance(aggregate, dict) else None
        windows = [item for item in draft.get("source_windows", []) or [] if isinstance(item, dict)]
        if not windows and isinstance(aggregate, dict):
            windows = [aggregate]
        for index, window in enumerate(windows):
            record = _window_from_event(window, fallback_source)
            if not record:
                continue
            out.append({
                "draft_name": draft.get("draft_name") or draft.get("draft_id"),
                "draft_id": draft.get("draft_id") or draft.get("draft_name"),
                "qa_status": draft.get("qa_status"),
                "review_required_reasons": draft.get("review_required_reasons") or [],
                "qa_gate": draft.get("qa_gate"),
                "events": draft.get("events") or [],
                "source_window_index": index,
                **record,
            })
    return out


def _detections(debug_dir: Path) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    for path in sorted((debug_dir / "sidecars").glob("*.perception.json")):
        payload = _read_json(path)
        source = payload.get("source_video") or path.name.replace(".perception.json", "")
        for item in payload.get("detections", []) or []:
            if isinstance(item, dict):
                detections.append({**item, "_source_video": source})
    return detections


def _time(item: dict[str, Any]) -> float | None:
    try:
        return float(item.get("time_sec"))
    except (TypeError, ValueError):
        return None


def _track(item: dict[str, Any]) -> str | None:
    value = item.get("track_id")
    if value is None:
        value = item.get("tracker_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _counts_for_record(record: dict[str, Any], detections: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for detection in detections:
        if not _sources_match(detection.get("_source_video"), record.get("source_video")):
            continue
        time_sec = _time(detection)
        track_id = _track(detection)
        if time_sec is None or track_id is None:
            continue
        if record["start"] <= time_sec <= record["end"]:
            counts[track_id] += 1
    return counts


def _window_issue(record: dict[str, Any], counts: Counter[str]) -> dict[str, Any] | None:
    total = sum(counts.values())
    if total < MIN_DETECTIONS or len(counts) < MIN_VISIBLE_TRACKS:
        return None
    primary, primary_count = counts.most_common(1)[0]
    dominance = _safe_div(primary_count, total)
    if dominance > MAX_PRIMARY_DOMINANCE:
        return None
    return {
        "draft": record["draft_name"],
        "source_video": _source_name(record["source_video"]),
        "source_window": {"index": record["source_window_index"], "start": record["start"], "end": record["end"]},
        "detection_count": total,
        "visible_track_count": len(counts),
        "visible_track_ids": sorted(counts.keys()),
        "track_detection_counts": dict(sorted(counts.items())),
        "primary_track_id": primary,
        "primary_track_detections": primary_count,
        "primary_track_dominance_ratio": round(dominance, 3),
    }


def _is_review_blocked(record: dict[str, Any]) -> bool:
    if str(record.get("qa_status") or "").lower() == "review_required":
        return True
    reasons = [str(item).upper() for item in record.get("review_required_reasons") or []]
    if any(reason in {"MULTI_PERSON_CLIP", "QA_REVIEW_REQUIRED"} for reason in reasons):
        return True
    qa_gate = record.get("qa_gate") if isinstance(record.get("qa_gate"), dict) else {}
    if qa_gate.get("qa_review_required") is True:
        return True
    for defect in qa_gate.get("defects", []) or []:
        if isinstance(defect, dict) and str(defect.get("type") or "").upper() == "MULTI_PERSON_CLIP" and defect.get("blocking") is True:
            return True
    for event in record.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        gate = event.get("multi_person_clip_gate") if isinstance(event.get("multi_person_clip_gate"), dict) else None
        if gate and gate.get("decision") == "review_required":
            return True
    return False


def append_summary(report_path: Path, trace_path: Path, debug_dir: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    trace = _read_json(trace_path)
    detections = _detections(debug_dir)
    issues: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    unblocked: list[dict[str, Any]] = []
    records = _records(trace)
    for record in records:
        issue = _window_issue(record, _counts_for_record(record, detections))
        if not issue:
            continue
        issues.append(issue)
        if _is_review_blocked(record):
            blocked.append(issue)
        else:
            unblocked.append(issue)
    metrics = report.setdefault("metrics", {})
    draft_count = int(metrics.get("draft_count") or max(1, len({record.get("draft_id") for record in records})))
    metrics["mixed_subject_likely_window_count"] = len(issues)
    metrics["mixed_subject_blocked_window_count"] = len(blocked)
    metrics["mixed_subject_unblocked_window_count"] = len(unblocked)
    metrics["mixed_subject_violation_rate"] = _safe_div(len(unblocked), max(draft_count, 1))
    report["mixed_subject_likely_windows"] = issues
    report["mixed_subject_blocked_windows"] = blocked
    report["mixed_subject_unblocked_windows"] = unblocked
    report["alerts"] = [
        item for item in report.get("alerts", [])
        if not (isinstance(item, dict) and item.get("metric") == "mixed_subject_violation_rate")
    ]
    report["bug_classifications"] = [
        item for item in report.get("bug_classifications", [])
        if not (isinstance(item, dict) and item.get("code") == "BUG_MIXED_SUBJECT_LIKELY")
    ]
    if unblocked:
        report.setdefault("alerts", []).append({
            "metric": "mixed_subject_violation_rate",
            "severity": "hard_block",
            "reason": "one or more drafts contain multiple significant visible tracks without review-required blocking",
        })
        report.setdefault("bug_classifications", []).append({
            "code": "BUG_MIXED_SUBJECT_LIKELY",
            "evidence": f"{len(unblocked)} unblocked mixed-subject source-window(s)",
        })
    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["mixed_subject_review_policy_ready"] = True
    if any(isinstance(item, dict) and item.get("severity") == "hard_block" for item in report.get("alerts", [])):
        report["status"] = "fail"
    elif any(isinstance(item, dict) and item.get("severity") == "inconclusive" for item in report.get("alerts", [])):
        report["status"] = "inconclusive"
    else:
        report["status"] = "pass"
    _write_json(report_path, report)
    return report


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: append_review_window_summary_to_report.py RUN_QUALITY_REPORT_JSON DRAFT_DECISION_TRACE_JSON DEBUG_DIR", file=sys.stderr)
        return 2
    report = append_summary(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    metrics = report.get("metrics", {})
    print(
        "review-window summary "
        f"detected={metrics.get('mixed_subject_likely_window_count', 0)} "
        f"blocked={metrics.get('mixed_subject_blocked_window_count', 0)} "
        f"unblocked={metrics.get('mixed_subject_unblocked_window_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

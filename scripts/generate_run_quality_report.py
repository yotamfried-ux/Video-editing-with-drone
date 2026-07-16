#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
_TRACE_FILENAMES = {
    "candidate_decision_ledger.json",
    "candidate_decision_ledger.jsonl",
    "decision_trace.json",
    "draft_decision_trace.json",
}
_DROPPED_REASON_KEYS = {"dropped_reason", "drop_reason", "reject_reason"}
_RUNTIME_BUG_TOKENS = {
    "torchvision.ops.nms": "BUG_RUNTIME_ENVIRONMENT",
    "torchvision::nms": "BUG_RUNTIME_ENVIRONMENT",
    "AutoUpdate success": "BUG_RUNTIME_ENVIRONMENT",
    "Restart runtime or rerun command": "BUG_RUNTIME_ENVIRONMENT",
    "TimeoutExpired": "BUG_RUNTIME_ENVIRONMENT",
    "timed out": "BUG_RUNTIME_ENVIRONMENT",
}
_OVERLAP_MIN_SECONDS = 2.0
_OVERLAP_MIN_RATIO = 0.5
_MIXED_SUBJECT_MIN_DETECTIONS = 4
_MIXED_SUBJECT_MIN_TRACKS = 2
_MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE = 0.7
_SHORT_TRACK_SECONDS = 2.0
_SHORT_TRACK_RATE_ALERT = 0.5
_MIN_TRACKS_FOR_FRAGMENTATION = 10
# Only "strong" evidence (cross-source track_id or an explicit, non-generated
# athlete_id match — see pipeline/athlete_canonicalization.py) is deterministic
# enough to flag a cross-draft duplicate here. Weak/single_source ids are
# per-source fallback hashes and are excluded so tracker fragmentation cannot
# produce a false positive.
_DUPLICATE_ATHLETE_STRONG_STATUSES = {"strong"}


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _iter_json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in sorted(root.rglob("*.json")) if path.is_file() and "pipeline-debug" not in path.parts]


def _is_video_file(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _is_draft_file(path: str) -> bool:
    name = Path(path).name.lower()
    return _is_video_file(path) and (name.startswith("draft") or "draft_" in name or "draft-" in name)


def _is_sidecar(path: Path) -> bool:
    return path.name.endswith(".perception.json")


def _source_name(value: Any) -> str:
    if value is None:
        return ""
    return Path(str(value)).name


def _sources_match(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left) == str(right) or _source_name(left) == _source_name(right)


def _bbox_invalid(detection: dict[str, Any]) -> bool:
    bbox = detection.get("bbox_xyxy") or detection.get("xyxy")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return True
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
        width = float(detection.get("frame_width") or 0)
        height = float(detection.get("frame_height") or 0)
    except (TypeError, ValueError):
        return True
    if not all(math.isfinite(value) for value in [x1, y1, x2, y2, width, height]):
        return True
    if width <= 0 or height <= 0:
        return True
    if x2 <= x1 or y2 <= y1:
        return True
    return x1 < 0 or y1 < 0 or x2 > width or y2 > height


def _time_invalid(detection: dict[str, Any]) -> bool:
    try:
        frame_index = int(detection.get("frame_index"))
        time_sec = float(detection.get("time_sec"))
    except (TypeError, ValueError):
        return True
    return frame_index < 0 or time_sec < 0 or not math.isfinite(time_sec)


def _time_sec(detection: dict[str, Any]) -> float | None:
    try:
        value = float(detection.get("time_sec"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _track_id(detection: dict[str, Any]) -> str | None:
    value = detection.get("track_id")
    if value is None:
        value = detection.get("tracker_id")
    if value is None:
        return None
    return str(value)


def _load_sidecars(tmp_root: Path, debug_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    paths = {_path.resolve() for _path in _iter_json_files(tmp_root) if _is_sidecar(_path)}
    copied = debug_dir / "sidecars"
    paths.update({_path.resolve() for _path in _iter_json_files(copied) if _is_sidecar(_path)})
    payloads: list[dict[str, Any]] = []
    schema_errors: list[str] = []
    for path in sorted(paths):
        try:
            payload = _read_json(path)
        except Exception as exc:
            schema_errors.append(f"{path}: {exc}")
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("detections", []), list):
            schema_errors.append(f"{path}: invalid sidecar schema")
            continue
        payloads.append({**payload, "_path": str(path)})
    return payloads, schema_errors


def _load_summary(debug_dir: Path) -> dict[str, Any]:
    path = debug_dir / "summary.json"
    if not path.exists():
        return {"files": [], "exit_code": None}
    try:
        payload = _read_json(path)
    except Exception:
        return {"files": [], "exit_code": None, "summary_parse_error": True}
    return payload if isinstance(payload, dict) else {"files": [], "exit_code": None, "summary_parse_error": True}


def _load_draft_trace(tmp_root: Path, debug_dir: Path) -> dict[str, Any]:
    for path in [tmp_root / "draft_decision_trace.json", debug_dir / "draft_decision_trace.json"]:
        if not path.exists():
            continue
        try:
            payload = _read_json(path)
        except Exception:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("drafts", []), list):
            return payload
    return {"drafts": []}


def _contains_trace(paths: list[Path], draft_trace: dict[str, Any]) -> bool:
    if isinstance(draft_trace.get("drafts"), list) and draft_trace.get("drafts"):
        return True
    return any(path.name in _TRACE_FILENAMES or "decision_trace" in path.name for path in paths)


def _contains_dropped_reason(paths: list[Path]) -> bool:
    for path in paths:
        if path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(key in text for key in _DROPPED_REASON_KEYS):
            return True
    return False


def _log_text(debug_dir: Path) -> str:
    path = debug_dir / "run_tracked.log"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _distribution_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {"count": len(values), "min": min(values), "max": max(values), "mean": sum(values) / len(values)}


def _drafts_with_source_window(draft_trace: dict[str, Any]) -> int:
    count = 0
    for draft in draft_trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        window = draft.get("source_window") or {}
        if isinstance(window, dict) and isinstance(window.get("start"), (int, float)) and isinstance(window.get("end"), (int, float)):
            count += 1
    return count


def _source_window_records(draft_trace: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for draft in draft_trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        window = draft.get("source_window") or {}
        if not isinstance(window, dict):
            continue
        start = window.get("start")
        end = window.get("end")
        source_video = window.get("source_video")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if not source_video or end <= start:
            continue
        records.append({
            "draft_id": draft.get("draft_id") or draft.get("draft_name"),
            "draft_name": draft.get("draft_name") or draft.get("draft_id"),
            "source_video": str(source_video),
            "start": float(start),
            "end": float(end),
            "duration": float(end) - float(start),
        })
    return records


def _source_window_overlap_duplicates(draft_trace: dict[str, Any]) -> list[dict[str, Any]]:
    records = _source_window_records(draft_trace)
    duplicates: list[dict[str, Any]] = []
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            if left["source_video"] != right["source_video"]:
                continue
            overlap = min(left["end"], right["end"]) - max(left["start"], right["start"])
            if overlap <= 0:
                continue
            shorter = min(left["duration"], right["duration"])
            ratio = _safe_div(overlap, shorter)
            if overlap >= _OVERLAP_MIN_SECONDS and ratio >= _OVERLAP_MIN_RATIO:
                duplicates.append({
                    "left_draft": left["draft_name"],
                    "right_draft": right["draft_name"],
                    "source_video": left["source_video"],
                    "left_window": {"start": left["start"], "end": left["end"]},
                    "right_window": {"start": right["start"], "end": right["end"]},
                    "overlap_seconds": round(overlap, 3),
                    "overlap_ratio_of_shorter": round(ratio, 3),
                })
    return duplicates


def _detections_in_window(detections: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for detection in detections:
        if not _sources_match(detection.get("_source_video"), record.get("source_video")):
            continue
        time_sec = _time_sec(detection)
        if time_sec is None:
            continue
        if record["start"] <= time_sec <= record["end"]:
            out.append(detection)
    return out


def _mixed_subject_windows(draft_trace: dict[str, Any], detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mixed: list[dict[str, Any]] = []
    for record in _source_window_records(draft_trace):
        window_detections = _detections_in_window(detections, record)
        track_counts = Counter(_track_id(item) for item in window_detections if _track_id(item) is not None)
        total = sum(track_counts.values())
        if total < _MIXED_SUBJECT_MIN_DETECTIONS or len(track_counts) < _MIXED_SUBJECT_MIN_TRACKS:
            continue
        primary_track, primary_count = track_counts.most_common(1)[0]
        dominance = _safe_div(primary_count, total)
        if dominance <= _MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE:
            mixed.append({
                "draft": record["draft_name"],
                "source_video": record["source_video"],
                "source_window": {"start": record["start"], "end": record["end"]},
                "detection_count": total,
                "visible_track_count": len(track_counts),
                "visible_track_ids": sorted(track_counts.keys()),
                "track_detection_counts": dict(sorted(track_counts.items())),
                "primary_track_id": primary_track,
                "primary_track_detections": primary_count,
                "primary_track_dominance_ratio": round(dominance, 3),
            })
    return mixed


def _track_fragmentation_summary(detections: list[dict[str, Any]]) -> dict[str, Any]:
    track_times: dict[str, list[float]] = defaultdict(list)
    for detection in detections:
        track_id = _track_id(detection)
        time_sec = _time_sec(detection)
        if track_id is None or time_sec is None:
            continue
        track_times[track_id].append(time_sec)
    durations: list[float] = []
    counts: list[int] = []
    short_tracks: list[dict[str, Any]] = []
    for track_id, times in sorted(track_times.items()):
        if not times:
            continue
        duration = max(times) - min(times)
        durations.append(duration)
        counts.append(len(times))
        if duration < _SHORT_TRACK_SECONDS:
            short_tracks.append({
                "track_id": track_id,
                "first_time_sec": round(min(times), 3),
                "last_time_sec": round(max(times), 3),
                "duration_sec": round(duration, 3),
                "detection_count": len(times),
            })
    track_count = len(track_times)
    return {
        "track_count": track_count,
        "short_track_count": len(short_tracks),
        "short_track_rate": _safe_div(len(short_tracks), track_count),
        "track_duration_distribution": _distribution_summary(durations),
        "detections_per_track_distribution": _distribution_summary([float(value) for value in counts]),
        "short_track_threshold_sec": _SHORT_TRACK_SECONDS,
        "top_short_tracks": short_tracks[:25],
    }


def _fragmentation_likely(fragmentation: dict[str, Any]) -> bool:
    return (
        int(fragmentation.get("track_count") or 0) >= _MIN_TRACKS_FOR_FRAGMENTATION
        and float(fragmentation.get("short_track_rate") or 0.0) >= _SHORT_TRACK_RATE_ALERT
    )


def _duplicate_athlete_likely_drafts(draft_trace: dict[str, Any]) -> list[dict[str, Any]]:
    athlete_to_drafts: dict[str, set[str]] = defaultdict(set)
    for draft in draft_trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        draft_id = draft.get("draft_id") or draft.get("draft_name")
        if not draft_id:
            continue
        for window in draft.get("source_windows", []) or []:
            if not isinstance(window, dict):
                continue
            athlete_id = window.get("athlete_id")
            status = window.get("athlete_canonical_evidence_status")
            if athlete_id and status in _DUPLICATE_ATHLETE_STRONG_STATUSES:
                athlete_to_drafts[str(athlete_id)].add(str(draft_id))
    return [
        {"athlete_id": athlete_id, "draft_ids": sorted(draft_ids)}
        for athlete_id, draft_ids in sorted(athlete_to_drafts.items())
        if len(draft_ids) > 1
    ]


def build_report(debug_dir: Path, tmp_root: Path, exit_code: int | None = None) -> dict[str, Any]:
    summary = _load_summary(debug_dir)
    files_from_summary = summary.get("files") if isinstance(summary.get("files"), list) else []
    summary_paths = [str(item.get("path")) for item in files_from_summary if isinstance(item, dict) and item.get("path")]
    all_tmp_json = _iter_json_files(tmp_root)
    sidecars, sidecar_schema_errors = _load_sidecars(tmp_root, debug_dir)
    draft_trace = _load_draft_trace(tmp_root, debug_dir)
    trace_drafts = [d for d in draft_trace.get("drafts", []) or [] if isinstance(d, dict)]
    drafts_with_source_window = _drafts_with_source_window(draft_trace)
    overlap_duplicates = _source_window_overlap_duplicates(draft_trace)
    detections: list[dict[str, Any]] = []
    for sidecar in sidecars:
        source_video = sidecar.get("source_video")
        for item in sidecar.get("detections", []) or []:
            if isinstance(item, dict):
                detections.append({**item, "_source_video": source_video, "_sidecar_path": sidecar.get("_path")})
    mixed_windows = _mixed_subject_windows(draft_trace, detections)
    fragmentation = _track_fragmentation_summary(detections)
    duplicate_athlete_drafts = _duplicate_athlete_likely_drafts(draft_trace)

    video_count = sum(1 for path in summary_paths if _is_video_file(path))
    draft_count = max(sum(1 for path in summary_paths if _is_draft_file(path)), len(trace_drafts))
    sidecar_count = len(sidecars)
    detection_count = len(detections)
    missing_track_count = sum(1 for item in detections if _track_id(item) is None)
    invalid_bbox_count = sum(1 for item in detections if _bbox_invalid(item))
    invalid_time_count = sum(1 for item in detections if _time_invalid(item))
    confidence_values = [float(item["confidence"]) for item in detections if item.get("confidence") is not None]
    unique_tracks = Counter(_track_id(item) for item in detections if _track_id(item) is not None)
    has_trace = _contains_trace(all_tmp_json, draft_trace)
    has_dropped_reasons = _contains_dropped_reason(all_tmp_json)
    log = _log_text(debug_dir)
    possible_pairs = draft_count * (draft_count - 1) / 2

    metrics: dict[str, Any] = {
        "exit_code": exit_code if exit_code is not None else summary.get("exit_code"),
        "video_count": video_count,
        "draft_count": draft_count,
        "sidecar_count": sidecar_count,
        "detection_count": detection_count,
        "unique_track_count": len(unique_tracks),
        "draft_metadata_count": len(trace_drafts),
        "draft_source_window_coverage_rate": _safe_div(drafts_with_source_window, max(draft_count, 1)),
        "source_window_overlap_pair_count": len(overlap_duplicates),
        "source_window_overlap_duplicate_rate": _safe_div(len(overlap_duplicates), possible_pairs),
        "mixed_subject_likely_window_count": len(mixed_windows),
        "mixed_subject_violation_rate": _safe_div(len(mixed_windows), max(draft_count, 1)),
        "duplicate_athlete_likely_draft_count": len(duplicate_athlete_drafts),
        "duplicate_athlete_violation_rate": _safe_div(len(duplicate_athlete_drafts), max(draft_count, 1)),
        "track_fragmentation_rate": fragmentation["short_track_rate"],
        "short_track_count": fragmentation["short_track_count"],
        "short_track_rate": fragmentation["short_track_rate"],
        "sidecar_missing_rate": 1.0 if video_count > 0 and sidecar_count == 0 else 0.0,
        "sidecar_schema_error_rate": _safe_div(len(sidecar_schema_errors), max(sidecar_count + len(sidecar_schema_errors), 1)),
        "track_id_missing_rate": _safe_div(missing_track_count, detection_count),
        "bbox_out_of_bounds_rate": _safe_div(invalid_bbox_count, detection_count),
        "invalid_time_window_rate": _safe_div(invalid_time_count, detection_count),
        "artifact_upload_missing_rate": 1.0 if not debug_dir.exists() or not (debug_dir / "summary.json").exists() else 0.0,
        "draft_without_decision_trace_rate": 1.0 if draft_count > 0 and not has_trace else 0.0,
        "no_drafts_with_candidates_rate": 0.0,
        "confidence_distribution": _distribution_summary(confidence_values),
        "detections_per_video": _safe_div(detection_count, max(video_count, 1)),
        "tracks_per_video": _safe_div(len(unique_tracks), max(video_count, 1)),
    }

    alerts: list[dict[str, Any]] = []
    classifications: list[dict[str, Any]] = []

    def add_alert(metric: str, severity: str, reason: str) -> None:
        alerts.append({"metric": metric, "severity": severity, "reason": reason})

    if metrics["sidecar_missing_rate"] > 0:
        add_alert("sidecar_missing_rate", "hard_block", "perception sidecar missing while videos exist")
    if metrics["sidecar_schema_error_rate"] > 0:
        add_alert("sidecar_schema_error_rate", "hard_block", "one or more sidecars failed schema validation")
    if metrics["track_id_missing_rate"] > 0:
        add_alert("track_id_missing_rate", "hard_block", "production detections must include track_id")
    if metrics["bbox_out_of_bounds_rate"] > 0:
        add_alert("bbox_out_of_bounds_rate", "hard_block", "one or more detections have invalid bboxes")
    if metrics["invalid_time_window_rate"] > 0:
        add_alert("invalid_time_window_rate", "hard_block", "one or more detections have invalid frame/time metadata")
    if metrics["draft_without_decision_trace_rate"] > 0:
        add_alert("draft_without_decision_trace_rate", "hard_block", "drafts exist without candidate decision trace")
        classifications.append({"code": "BUG_SELECTION_BYPASSED_EVIDENCE", "evidence": "draft exists without candidate decision trace"})
    if draft_count > 0 and metrics["draft_source_window_coverage_rate"] < 1.0:
        add_alert("draft_source_window_coverage_rate", "inconclusive", "one or more drafts lack source-window metadata")
    if overlap_duplicates:
        add_alert("source_window_overlap_duplicate_rate", "hard_block", "two or more drafts strongly overlap the same source window")
        classifications.append({"code": "BUG_DUPLICATE_MOMENT_LIKELY", "evidence": f"{len(overlap_duplicates)} overlapping draft source-window pair(s)"})
    if mixed_windows:
        add_alert("mixed_subject_violation_rate", "hard_block", "one or more drafts contain multiple significant visible tracks with low primary-track dominance")
        classifications.append({"code": "BUG_MIXED_SUBJECT_LIKELY", "evidence": f"{len(mixed_windows)} mixed-subject source-window(s)"})
    if duplicate_athlete_drafts:
        add_alert("duplicate_athlete_violation_rate", "hard_block", "the same athlete, identified by deterministic cross-source evidence, is the subject of multiple separate drafts")
        classifications.append({"code": "BUG_DUPLICATE_ATHLETE_LIKELY", "evidence": f"{len(duplicate_athlete_drafts)} athlete id(s) spanning multiple drafts"})
    if _fragmentation_likely(fragmentation):
        add_alert("track_fragmentation_rate", "hard_block", "tracker produced many short-lived track ids")
        classifications.append({"code": "BUG_TRACKING_FRAGMENTATION_LIKELY", "evidence": f"short_track_rate={fragmentation['short_track_rate']:.3f} track_count={fragmentation['track_count']}"})
    if not has_dropped_reasons:
        add_alert("missing_dropped_reasons", "inconclusive", "dropped candidate reasons are not available")
        classifications.append({"code": "BUG_RECALL_UNKNOWN", "evidence": "missing dropped candidate reasons"})
    for token, code in _RUNTIME_BUG_TOKENS.items():
        if token in log:
            add_alert("runtime_log", "hard_block", f"runtime log contains {token}")
            classifications.append({"code": code, "evidence": token})

    status = "pass"
    if any(alert["severity"] == "hard_block" for alert in alerts):
        status = "fail"
    elif any(alert["severity"] == "inconclusive" for alert in alerts):
        status = "inconclusive"

    return {
        "schema_version": "sportreel.run_quality_report.v1",
        "status": status,
        "summary": {"debug_dir": str(debug_dir), "tmp_root": str(tmp_root), "files_observed": len(summary_paths), "json_files_observed": len(all_tmp_json)},
        "metrics": metrics,
        "alerts": alerts,
        "bug_classifications": classifications,
        "sidecar_schema_errors": sidecar_schema_errors,
        "draft_decision_trace": {"schema_version": draft_trace.get("schema_version"), "draft_count": len(trace_drafts), "drafts_with_source_window": drafts_with_source_window},
        "source_window_overlap_duplicates": overlap_duplicates,
        "mixed_subject_likely_windows": mixed_windows,
        "track_fragmentation": fragmentation,
        "duplicate_athlete_likely_drafts": duplicate_athlete_drafts,
        "implementation_gaps": {
            "candidate_decision_ledger_present": has_trace,
            "dropped_reasons_present": has_dropped_reasons,
            "draft_source_window_metadata_present": bool(trace_drafts),
            "mixed_subject_metric_ready": True,
            "track_fragmentation_metric_ready": True,
            "duplicate_athlete_metric_ready": True,
        },
    }


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: generate_run_quality_report.py DEBUG_DIR TMP_ROOT [EXIT_CODE]", file=sys.stderr)
        return 2
    debug_dir = Path(sys.argv[1])
    tmp_root = Path(sys.argv[2])
    exit_code = None if len(sys.argv) < 4 else int(sys.argv[3])
    report = build_report(debug_dir, tmp_root, exit_code)
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "run_quality_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"run quality report status={report['status']} alerts={len(report['alerts'])} bugs={len(report['bug_classifications'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

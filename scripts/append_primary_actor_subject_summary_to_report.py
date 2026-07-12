#!/usr/bin/env python3
"""Replace coarse track-count mixed-subject alerts with primary-actor evidence.

Extra people are normal in sport. A final cut is a mixed-subject violation only
when its explicit actor gate requires review. Frame-level statistics remain in the
report as evidence, but sequential/background tracks do not create a hard block.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_ALLOWED_DECISIONS = {"allowed_primary_actor_clear", "allowed_social_moment"}
_BLOCKING_DECISIONS = {"review_required", "blocked_review_required"}
_MIXED_ALERT_METRICS = {"mixed_subject_violation_rate", "mixed_subject_policy_evidence_rate"}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".primary-actor.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _source_name(value: Any) -> str:
    return Path(str(value or "")).name


def _sources_match(left: Any, right: Any) -> bool:
    return bool(left and right) and (str(left) == str(right) or _source_name(left) == _source_name(right))


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _track_id(item: dict[str, Any]) -> str | None:
    value = item.get("track_id", item.get("tracker_id"))
    return None if value is None else str(value)


def _load_detections(sidecar_dir: Path) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    if not sidecar_dir.exists():
        return detections
    for path in sorted(sidecar_dir.rglob("*.perception.json")):
        payload = _read(path)
        source = payload.get("source_video")
        for item in payload.get("detections", []) or []:
            if isinstance(item, dict):
                detections.append({**item, "_source_video": source, "_sidecar_path": str(path)})
    return detections


def _window_records(trace: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for draft in trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        draft_name = str(draft.get("draft_name") or draft.get("draft_id") or "unknown_draft")
        windows = [item for item in draft.get("source_windows", []) or [] if isinstance(item, dict)]
        if not windows and isinstance(draft.get("source_window"), dict):
            windows = [draft["source_window"]]
        for index, window in enumerate(windows):
            start = _num(window.get("final_cut_start"))
            end = _num(window.get("final_cut_end"))
            if start is None:
                start = _num(window.get("start"))
            if end is None:
                end = _num(window.get("end"))
            source = window.get("source_video") or (draft.get("source_videos") or [None])[0]
            if start is None or end is None or end <= start or not source:
                continue
            records.append({
                "draft": draft_name,
                "window_index": index,
                "source_video": str(source),
                "start": start,
                "end": end,
                "person_id": window.get("person_id") or draft.get("person_id"),
                "athlete_id": window.get("athlete_id") or draft.get("athlete_id"),
                "track_id": window.get("track_id"),
                "subject_isolation_gate": window.get("subject_isolation_gate"),
                "multi_person_clip_gate": window.get("multi_person_clip_gate"),
            })
    return records


def _gate_for(record: dict[str, Any]) -> dict[str, Any] | None:
    subject = record.get("subject_isolation_gate")
    if isinstance(subject, dict) and subject.get("decision"):
        return subject
    multi = record.get("multi_person_clip_gate")
    if isinstance(multi, dict) and multi.get("decision"):
        return multi
    return None


def _primary_track(record: dict[str, Any], gate: dict[str, Any] | None) -> str | None:
    if gate:
        for key in ("declared_target_track_id", "primary_track_id", "primary_actor_id"):
            value = gate.get(key)
            if value is not None and str(value).strip():
                return str(value)
        primary_subject = str(gate.get("primary_subject_id") or "")
        if primary_subject.startswith("track_id:"):
            return primary_subject.split(":", 1)[1]
    value = record.get("track_id")
    return None if value is None else str(value)


def _frame_stats(record: dict[str, Any], detections: list[dict[str, Any]], primary: str | None) -> dict[str, Any]:
    frames: dict[str, set[str]] = defaultdict(set)
    for item in detections:
        if not _sources_match(item.get("_source_video"), record.get("source_video")):
            continue
        time_sec = _num(item.get("time_sec"))
        track = _track_id(item)
        if time_sec is None or track is None or not (record["start"] <= time_sec <= record["end"]):
            continue
        frame_index = item.get("frame_index")
        frame_key = f"frame:{frame_index}" if frame_index is not None else f"time:{time_sec:.3f}"
        frames[frame_key].add(track)

    track_frame_counts: Counter[str] = Counter()
    for tracks in frames.values():
        track_frame_counts.update(tracks)
    if primary is None and track_frame_counts:
        primary = track_frame_counts.most_common(1)[0][0]

    frame_count = len(frames)
    concurrent = sum(1 for tracks in frames.values() if len(tracks) > 1)
    primary_frames = sum(1 for tracks in frames.values() if primary is not None and primary in tracks)
    concurrent_without_primary = sum(
        1 for tracks in frames.values() if len(tracks) > 1 and (primary is None or primary not in tracks)
    )
    return {
        "sampled_frame_count": frame_count,
        "concurrent_person_frame_count": concurrent,
        "concurrent_person_frame_rate": round(concurrent / frame_count, 3) if frame_count else 0.0,
        "max_simultaneous_track_count": max((len(tracks) for tracks in frames.values()), default=0),
        "primary_track_id": primary,
        "primary_track_frame_count": primary_frames,
        "primary_track_frame_continuity": round(primary_frames / frame_count, 3) if frame_count else None,
        "concurrent_frames_without_primary_count": concurrent_without_primary,
        "visible_track_ids": sorted(track_frame_counts),
        "track_frame_counts": dict(sorted(track_frame_counts.items())),
    }


def _blocking_gate(gate: dict[str, Any] | None) -> bool:
    if not gate:
        return False
    if str(gate.get("decision") or "") in _BLOCKING_DECISIONS:
        return True
    defect = gate.get("defect")
    return isinstance(defect, dict) and defect.get("blocking") is True


def evaluate(trace: dict[str, Any], detections: list[dict[str, Any]]) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    for record in _window_records(trace):
        gate = _gate_for(record)
        decision = str((gate or {}).get("decision") or "")
        policy_explicit = bool(decision)
        violation = _blocking_gate(gate)
        primary = _primary_track(record, gate)
        stats = _frame_stats(record, detections, primary)
        evaluations.append({
            "draft": record["draft"],
            "window_index": record["window_index"],
            "source_video": record["source_video"],
            "final_cut_window": {"start": record["start"], "end": record["end"]},
            "person_id": record.get("person_id"),
            "athlete_id": record.get("athlete_id"),
            "policy_explicit": policy_explicit,
            "policy_decision": decision or "missing",
            "background_people_allowed": bool((gate or {}).get("background_people_allowed")) or decision in _ALLOWED_DECISIONS,
            "mixed_subject_violation": violation,
            "violation_reason": (gate or {}).get("reason") if violation else None,
            "ambiguity_reasons": list((gate or {}).get("ambiguity_reasons") or []),
            **stats,
        })
    violations = [item for item in evaluations if item["mixed_subject_violation"]]
    missing_policy = [item for item in evaluations if not item["policy_explicit"]]
    return {
        "evaluations": evaluations,
        "violations": violations,
        "missing_policy": missing_policy,
    }


def append_summary(report_path: Path, trace_path: Path, sidecar_dir: Path) -> dict[str, Any]:
    report = _read(report_path)
    trace = _read(trace_path)
    result = evaluate(trace, _load_detections(sidecar_dir))
    evaluations = result["evaluations"]
    violations = result["violations"]
    missing_policy = result["missing_policy"]

    alerts = [
        item for item in report.get("alerts", []) or []
        if not (isinstance(item, dict) and item.get("metric") in _MIXED_ALERT_METRICS)
    ]
    classifications = [
        item for item in report.get("bug_classifications", []) or []
        if not (isinstance(item, dict) and item.get("code") == "BUG_MIXED_SUBJECT_LIKELY")
    ]
    if violations:
        alerts.append({
            "metric": "mixed_subject_violation_rate",
            "severity": "hard_block",
            "reason": "one or more final cuts have an explicit primary-actor review-required decision",
        })
        classifications.append({
            "code": "BUG_MIXED_SUBJECT_LIKELY",
            "evidence": f"{len(violations)} final action window(s) blocked by primary-actor policy",
        })
    elif missing_policy:
        alerts.append({
            "metric": "mixed_subject_policy_evidence_rate",
            "severity": "inconclusive",
            "reason": "one or more final action windows lack an explicit primary-actor gate decision",
        })

    metrics = report.setdefault("metrics", {})
    metrics.update({
        "mixed_subject_likely_window_count": len(violations),
        "mixed_subject_violation_rate": round(len(violations) / len(evaluations), 3) if evaluations else 0.0,
        "mixed_subject_evaluated_window_count": len(evaluations),
        "mixed_subject_policy_explicit_window_count": len(evaluations) - len(missing_policy),
        "mixed_subject_policy_evidence_rate": round((len(evaluations) - len(missing_policy)) / len(evaluations), 3) if evaluations else 1.0,
        "background_people_allowed_window_count": sum(1 for item in evaluations if item["background_people_allowed"]),
    })
    report["alerts"] = alerts
    report["bug_classifications"] = classifications
    report["mixed_subject_likely_windows"] = violations
    report["primary_actor_subject_evaluations"] = evaluations
    gaps = report.setdefault("implementation_gaps", {})
    gaps.update({
        "mixed_subject_metric_ready": True,
        "mixed_subject_policy_explicit": not missing_policy,
        "mixed_subject_uses_final_cut_windows": True,
        "mixed_subject_uses_frame_level_concurrency": True,
    })
    report["status"] = (
        "fail" if any(item.get("severity") == "hard_block" for item in alerts)
        else "inconclusive" if any(item.get("severity") == "inconclusive" for item in alerts)
        else "pass"
    )
    _write(report_path, report)
    return report


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: append_primary_actor_subject_summary_to_report.py RUN_REPORT DRAFT_TRACE SIDECAR_DIR", file=sys.stderr)
        return 2
    report = append_summary(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    print(
        "primary actor subject summary appended "
        f"windows={report.get('metrics', {}).get('mixed_subject_evaluated_window_count', 0)} "
        f"violations={report.get('metrics', {}).get('mixed_subject_likely_window_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

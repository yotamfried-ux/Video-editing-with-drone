"""Canonical-track subject isolation gate for draft source windows.

This gate consumes the production perception sidecar and marks a draft window as
review-required when one athlete is not clearly dominant inside the actual cut
window. It does not invent detections: it only uses canonical track IDs already
written into the sidecar, while raw IDs remain preserved there for audit.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.multi_person_clip_gate import is_intentional_social_moment

DEFECT_TYPE = "MULTI_PERSON_CLIP"
MIN_DETECTIONS = 4
MIN_TRACKS = 2
MAX_PRIMARY_DOMINANCE = 0.70
NONCLIMAX_CAP_SEC = 11.0
SINGLE_CLIP_CAP_SEC = 15.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_name(value: Any) -> str:
    return Path(str(value or "")).name


def _sources_match(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left) == str(right) or _source_name(left) == _source_name(right)


def _track_id(detection: Any) -> str | None:
    if not isinstance(detection, object):
        return None
    value = getattr(detection, "tracker_id", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("track_id") or detection.get("tracker_id")
    return None if value is None else str(value)


def _time_sec(detection: Any) -> float | None:
    value = getattr(detection, "time_sec", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("time_sec")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def effective_cut_window(event: dict[str, Any]) -> tuple[float, float]:
    """Return the actual source window the editor cuts for this event."""
    start = _num(event.get("final_cut_start"), _num(event.get("start")))
    end = _num(event.get("final_cut_end"), _num(event.get("end"), start))
    if end < start:
        start, end = end, start
    duration = end - start
    if duration <= 0:
        return start, end
    if event.get("_is_climax"):
        cap = _num(event.get("_cap_dur"), 0.0)
        if cap > 0:
            end = min(end, start + cap)
    elif duration > NONCLIMAX_CAP_SEC:
        start = round(end - NONCLIMAX_CAP_SEC, 2)
    if event.get("_single_clip_cap") and end - start > SINGLE_CLIP_CAP_SEC:
        end = start + SINGLE_CLIP_CAP_SEC
    return round(start, 3), round(end, 3)


def with_effective_cut_window(event: dict[str, Any]) -> dict[str, Any]:
    start, end = effective_cut_window(event)
    return {**event, "final_cut_start": start, "final_cut_end": end}


def _detections_for_event(event: dict[str, Any], detections: list[Any], source_video: str) -> list[Any]:
    start, end = effective_cut_window(event)
    source = event.get("_src") or event.get("source") or event.get("source_video") or source_video
    out: list[Any] = []
    for detection in detections:
        det_source = getattr(detection, "source_video", None)
        if det_source is None and isinstance(detection, dict):
            det_source = detection.get("source_video") or detection.get("_source_video")
        if det_source and source and not _sources_match(det_source, source):
            continue
        time_sec = _time_sec(detection)
        if time_sec is None:
            continue
        if start <= time_sec <= end:
            out.append(detection)
    return out


def build_subject_gate(event: dict[str, Any], detections: list[Any], index: int, *, source_video: str = "") -> dict[str, Any] | None:
    window_detections = _detections_for_event(event, detections, source_video)
    counts = Counter(_track_id(item) for item in window_detections if _track_id(item) is not None)
    total = sum(counts.values())
    if total < MIN_DETECTIONS or len(counts) < MIN_TRACKS:
        return None
    primary_track, primary_count = counts.most_common(1)[0]
    dominance = primary_count / total if total else 0.0
    if dominance > MAX_PRIMARY_DOMINANCE:
        return None
    social = is_intentional_social_moment(event)
    start, end = effective_cut_window(event)
    gate = {
        "decision": "allowed_social_moment" if social else "review_required",
        "reason": "intentional_social_moment" if social else "low_primary_track_dominance",
        "event_id": str(event.get("event_id") or event.get("id") or f"event_{index:03d}"),
        "source_video": _source_name(event.get("_src") or event.get("source") or event.get("source_video") or source_video),
        "source_window": {"start": start, "end": end},
        "detection_count": total,
        "visible_track_count": len(counts),
        "visible_track_ids": sorted(counts.keys()),
        "track_detection_counts": dict(sorted(counts.items())),
        "primary_track_id": primary_track,
        "primary_track_detections": primary_count,
        "primary_track_dominance_ratio": round(dominance, 3),
        "dominance_threshold": MAX_PRIMARY_DOMINANCE,
    }
    if not social:
        gate["defect"] = {
            "type": DEFECT_TYPE,
            "severity": "critical",
            "blocking": True,
            "event_id": gate["event_id"],
            "source_video": gate["source_video"],
            "note": "source window contains multiple significant canonical tracks; operator review required before approval",
            "primary_track_id": primary_track,
            "visible_track_ids": sorted(counts.keys()),
            "primary_track_dominance_ratio": round(dominance, 3),
        }
    return gate


def _merge_qa_gate(event: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    defect = gate.get("defect")
    if not defect:
        return event
    qa_gate = dict(event.get("qa_gate") or {})
    defects = [*qa_gate.get("defects", [])]
    defects.append(defect)
    reasons = [*qa_gate.get("review_required_reasons", [])]
    if DEFECT_TYPE not in reasons:
        reasons.append(DEFECT_TYPE)
    blocked = [*qa_gate.get("approval_blocked_reasons", [])]
    block_reason = f"{DEFECT_TYPE}: {defect.get('note')}"
    if block_reason not in blocked:
        blocked.append(block_reason)
    qa_gate.update({
        "decision": "blocked_review_required",
        "final_verdict": "FAIL",
        "qa_review_required": True,
        "critical_defect_count": max(1, int(qa_gate.get("critical_defect_count") or 0) + 1),
        "review_required_reasons": reasons,
        "approval_blocked_reasons": blocked,
        "defects": defects,
        "overall": qa_gate.get("overall") or "source window contains multiple significant canonical tracks",
    })
    return {**event, "qa_gate": qa_gate}


def annotate_subject_events(events: list[dict[str, Any]], *, source_video: str = "", athlete_label: str = "") -> list[dict[str, Any]]:
    try:
        from pipeline.perception.runtime import load_sidecar_detections
        detections = load_sidecar_detections(source_video) if source_video else []
    except Exception:
        detections = []
    if not detections:
        return [with_effective_cut_window(event) if isinstance(event, dict) else event for event in events or []]
    annotated: list[dict[str, Any]] = []
    for index, event in enumerate(events or []):
        if not isinstance(event, dict):
            annotated.append(event)
            continue
        next_event = with_effective_cut_window(event)
        gate = build_subject_gate(next_event, detections, index, source_video=source_video)
        if gate is not None:
            next_event = {**next_event, "subject_isolation_gate": gate}
            next_event = _merge_qa_gate(next_event, gate)
        annotated.append(next_event)
    return annotated


def has_subject_isolation_defect(events: list[dict[str, Any]]) -> bool:
    for event in events or []:
        gate = event.get("subject_isolation_gate") if isinstance(event, dict) else None
        if isinstance(gate, dict) and gate.get("decision") == "review_required":
            return True
    return False

"""Canonical-track primary-actor continuity gate for source windows.

The sidecar may contain many people, especially in team sports. Additional tracks
are not defects. This gate blocks only when the athlete performing the action is
lost, switched, critically occluded, or cannot be identified among the tracks.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.multi_person_clip_gate import is_intentional_social_moment
from pipeline.primary_actor_policy import classify_primary_actor, merge_gate_defect_into_qa

DEFECT_TYPE = "PRIMARY_ACTOR_UNCLEAR"
MIN_DETECTIONS = 4
MIN_TRACKS = 2
MIN_PRIMARY_CONTINUITY = 0.50
NONCLIMAX_CAP_SEC = 11.0
SINGLE_CLIP_CAP_SEC = 15.0
_TRACK_KEYS = ("target_track_id", "primary_track_id", "athlete_track_id", "track_id")


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
    value = getattr(detection, "tracker_id", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("track_id") or detection.get("tracker_id")
    return None if value is None else str(value)


def _time_sec(detection: Any) -> float | None:
    value = getattr(detection, "time_sec", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("time_sec")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_source(event: dict[str, Any], fallback: str = "") -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or fallback or "")


def _sources_from_events(events: list[dict[str, Any]], fallback: str = "") -> list[str]:
    seen: set[str] = set()
    sources: list[str] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        source = _event_source(event, fallback)
        if source and source not in seen:
            seen.add(source)
            sources.append(source)
    if fallback and fallback not in seen:
        sources.append(fallback)
    return sources


def _load_detections_for_sources(events: list[dict[str, Any]], fallback_source: str = "") -> list[Any]:
    try:
        from pipeline.perception.runtime import load_sidecar_detections
    except Exception:
        return []
    detections: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    for source in _sources_from_events(events, fallback_source):
        try:
            source_detections = load_sidecar_detections(source)
        except Exception:
            source_detections = []
        for detection in source_detections:
            det_source = getattr(detection, "source_video", None)
            if det_source is None and isinstance(detection, dict):
                det_source = detection.get("source_video") or detection.get("_source_video")
            key = (str(det_source or source), str(_time_sec(detection)), str(_track_id(detection)))
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)
    return detections


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
    source = _event_source(event, source_video)
    out: list[Any] = []
    for detection in detections:
        det_source = getattr(detection, "source_video", None)
        if det_source is None and isinstance(detection, dict):
            det_source = detection.get("source_video") or detection.get("_source_video")
        if det_source and source and not _sources_match(det_source, source):
            continue
        time_sec = _time_sec(detection)
        if time_sec is not None and start <= time_sec <= end:
            out.append(detection)
    return out


def _declared_track(event: dict[str, Any]) -> str | None:
    for key in _TRACK_KEYS:
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _requested_track(event: dict[str, Any], counts: Counter[str]) -> str | None:
    declared = _declared_track(event)
    return declared if declared in counts else None


def _continuity_ratio(track_id: str, detections: list[Any]) -> float:
    all_times = {round(t, 3) for item in detections if (t := _time_sec(item)) is not None}
    primary_times = {
        round(t, 3)
        for item in detections
        if _track_id(item) == track_id and (t := _time_sec(item)) is not None
    }
    return len(primary_times) / len(all_times) if all_times else 0.0


def build_subject_gate(event: dict[str, Any], detections: list[Any], index: int, *, source_video: str = "") -> dict[str, Any] | None:
    window_detections = _detections_for_event(event, detections, source_video)
    counts: Counter[str] = Counter(
        track_id for item in window_detections if (track_id := _track_id(item)) is not None
    )
    total = sum(counts.values())
    if total < MIN_DETECTIONS:
        return None

    declared_track = _declared_track(event)
    declared_track_missing = bool(declared_track and declared_track not in counts)
    if not declared_track_missing and len(counts) < MIN_TRACKS:
        return None

    if declared_track_missing:
        primary_track = declared_track
        primary_count = 0
        dominance = 0.0
        continuity = 0.0
    else:
        primary_track = _requested_track(event, counts) or counts.most_common(1)[0][0]
        primary_count = counts[primary_track]
        dominance = primary_count / total if total else 0.0
        continuity = _continuity_ratio(primary_track, window_detections)

    social = is_intentional_social_moment(event)
    start, end = effective_cut_window(event)

    if declared_track_missing:
        classification_event = {
            **event,
            "primary_actor_lost": True,
            "primary_actor_clear": False,
            "actor_tracking_status": "target_lost",
        }
        classification = classify_primary_actor(
            classification_event,
            visible_subject_count=len(counts),
            primary_continuity_ratio=0.0,
        )
        classification["reason"] = "declared_target_track_absent_from_source_window"
        reasons = list(classification.get("ambiguity_reasons", []))
        if "declared_target_track_absent" not in reasons:
            reasons.append("declared_target_track_absent")
        classification["ambiguity_reasons"] = reasons
    elif social:
        classification = {
            "decision": "allowed_social_moment",
            "reason": "intentional_social_moment",
            "ambiguity_reasons": [],
            "background_people_allowed": True,
        }
    else:
        classification = classify_primary_actor(
            event,
            visible_subject_count=len(counts),
            primary_continuity_ratio=continuity,
        )

    gate = {
        **classification,
        "event_id": str(event.get("event_id") or event.get("id") or f"event_{index:03d}"),
        "source_video": _source_name(_event_source(event, source_video)),
        "source_window": {"start": start, "end": end},
        "detection_count": total,
        "visible_track_count": len(counts),
        "visible_track_ids": sorted(counts.keys()),
        "track_detection_counts": dict(sorted(counts.items())),
        "declared_target_track_id": declared_track,
        "declared_target_track_present": not declared_track_missing if declared_track else None,
        "primary_track_id": primary_track,
        "primary_track_detections": primary_count,
        "primary_track_dominance_ratio": round(dominance, 3),
        "primary_track_continuity_ratio": round(continuity, 3),
        "continuity_threshold": MIN_PRIMARY_CONTINUITY,
        "background_people_allowed": classification.get("decision") != "review_required" and len(counts) > 1,
    }
    if classification.get("decision") == "review_required":
        defect_type = str(classification.get("defect_type") or DEFECT_TYPE)
        note = (
            "declared target athlete is absent from the source window"
            if declared_track_missing
            else "primary athlete cannot be followed reliably through the action"
        )
        gate["defect"] = {
            "type": defect_type,
            "severity": "critical",
            "blocking": True,
            "event_id": gate["event_id"],
            "source_video": gate["source_video"],
            "note": note,
            "declared_target_track_id": declared_track,
            "declared_target_track_present": not declared_track_missing if declared_track else None,
            "primary_track_id": primary_track,
            "visible_track_ids": sorted(counts.keys()),
            "primary_track_continuity_ratio": round(continuity, 3),
            "ambiguity_reasons": classification.get("ambiguity_reasons", []),
        }
    return gate


def annotate_subject_events(events: list[dict[str, Any]], *, source_video: str = "", athlete_label: str = "") -> list[dict[str, Any]]:
    detections = _load_detections_for_sources([event for event in events or [] if isinstance(event, dict)], source_video)
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
            next_event = merge_gate_defect_into_qa(
                next_event,
                gate,
                default_defect_type=DEFECT_TYPE,
                overall_fallback="primary athlete continuity is uncertain",
            )
        annotated.append(next_event)
    return annotated


def has_subject_isolation_defect(events: list[dict[str, Any]]) -> bool:
    for event in events or []:
        gate = event.get("subject_isolation_gate") if isinstance(event, dict) else None
        if isinstance(gate, dict) and gate.get("decision") == "review_required":
            return True
    return False

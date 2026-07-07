"""Sidecar-backed mixed-subject policy.

The report can detect mixed-subject windows directly from perception sidecars,
but REVIEW metadata must also carry that decision so an operator cannot approve a
single-athlete draft that contains multiple significant visible tracks. This
module uses canonical track IDs from the perception sidecar to annotate events
before metadata is saved.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.perception.runtime import load_sidecar_detections

MIXED_SUBJECT_DEFECT = "MULTI_PERSON_CLIP"
MIXED_SUBJECT_MIN_DETECTIONS = 4
MIXED_SUBJECT_MIN_TRACKS = 2
MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE = 0.70


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source(event: dict[str, Any], default_source: str = "") -> str:
    value = event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or default_source
    return str(value or "")


def _event_window(event: dict[str, Any]) -> tuple[float, float]:
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    return min(start, end), max(start, end)


def _track_id(detection: Any) -> str | None:
    value = getattr(detection, "tracker_id", None)
    if value is None:
        value = getattr(detection, "track_id", None)
    return None if value is None else str(value)


def _load(cache: dict[str, list[Any]], source_video: str) -> list[Any]:
    if not source_video:
        return []
    if source_video not in cache:
        try:
            cache[source_video] = load_sidecar_detections(source_video)
        except Exception:
            cache[source_video] = []
    return cache[source_video]


def track_counts_for_event(event: dict[str, Any], source_video: str, cache: dict[str, list[Any]] | None = None) -> Counter[str]:
    detections = _load(cache if cache is not None else {}, source_video)
    start, end = _event_window(event)
    counts: Counter[str] = Counter()
    for detection in detections:
        track_id = _track_id(detection)
        if track_id is None:
            continue
        time_sec = _num(getattr(detection, "time_sec", None), -1.0)
        if start <= time_sec <= end:
            counts[track_id] += 1
    return counts


def summarize_event_subjects(event: dict[str, Any], source_video: str, cache: dict[str, list[Any]] | None = None) -> dict[str, Any]:
    counts = track_counts_for_event(event, source_video, cache)
    total = sum(counts.values())
    visible_ids = sorted(counts.keys())
    if not counts:
        return {
            "source_video": source_video,
            "source_window": {"start": event.get("start"), "end": event.get("end")},
            "detection_count": 0,
            "visible_track_count": 0,
            "visible_track_ids": [],
            "track_detection_counts": {},
            "mixed_subject": False,
            "decision": "no_tracker_detection",
        }
    primary_track, primary_count = counts.most_common(1)[0]
    dominance = primary_count / total if total else 0.0
    mixed = (
        total >= MIXED_SUBJECT_MIN_DETECTIONS
        and len(counts) >= MIXED_SUBJECT_MIN_TRACKS
        and dominance <= MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE
    )
    return {
        "source_video": source_video,
        "source_window": {"start": event.get("start"), "end": event.get("end")},
        "detection_count": total,
        "visible_track_count": len(counts),
        "visible_track_ids": visible_ids,
        "track_detection_counts": dict(sorted(counts.items())),
        "primary_track_id": primary_track,
        "primary_track_detections": primary_count,
        "primary_track_dominance_ratio": round(dominance, 3),
        "mixed_subject": mixed,
        "decision": "review_required" if mixed else "primary_track_dominant",
        "thresholds": {
            "min_detections": MIXED_SUBJECT_MIN_DETECTIONS,
            "min_tracks": MIXED_SUBJECT_MIN_TRACKS,
            "max_primary_dominance": MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE,
        },
    }


def annotate_event_with_subject_policy(event: dict[str, Any], source_video: str, cache: dict[str, list[Any]] | None = None) -> dict[str, Any]:
    summary = summarize_event_subjects(event, source_video, cache)
    if summary.get("detection_count", 0) <= 0:
        return event
    primary = summary.get("primary_track_id")
    annotated = {
        **event,
        "track_id": event.get("track_id") or primary,
        "primary_track_id": primary,
        "primary_track_dominance_ratio": summary.get("primary_track_dominance_ratio"),
        "mixed_subject_policy": summary,
    }
    if summary.get("mixed_subject"):
        visible_ids = summary.get("visible_track_ids", [])
        annotated.update({
            "visible_track_ids": visible_ids,
            "source_window_track_ids": visible_ids,
            "all_visible_track_ids": visible_ids,
            "track_detection_counts": summary.get("track_detection_counts", {}),
        })
    return annotated


def annotate_mixed_subject_events(events: list[dict[str, Any]], default_source: str = "") -> list[dict[str, Any]]:
    cache: dict[str, list[Any]] = {}
    annotated: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict):
            annotated.append(event)
            continue
        source_video = _source(event, default_source)
        next_event = annotate_event_with_subject_policy(event, source_video, cache)
        annotated.append(next_event)
    return annotated


def draft_blocks_mixed_subject(draft: dict[str, Any]) -> bool:
    qa_gate = draft.get("qa_gate") if isinstance(draft.get("qa_gate"), dict) else None
    reasons = {str(item).upper() for item in draft.get("review_required_reasons", []) or []}
    if MIXED_SUBJECT_DEFECT in reasons:
        return True
    if isinstance(qa_gate, dict):
        gate_reasons = {str(item).upper() for item in qa_gate.get("review_required_reasons", []) or []}
        if MIXED_SUBJECT_DEFECT in gate_reasons:
            return True
        for defect in qa_gate.get("defects", []) or []:
            if isinstance(defect, dict) and str(defect.get("type", "")).upper() == MIXED_SUBJECT_DEFECT:
                return True
    for event in draft.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        gate = event.get("multi_person_clip_gate") if isinstance(event.get("multi_person_clip_gate"), dict) else None
        if gate and gate.get("decision") == "review_required":
            return True
        policy = event.get("mixed_subject_policy") if isinstance(event.get("mixed_subject_policy"), dict) else None
        if policy and policy.get("decision") == "review_required":
            return True
    return False


def draft_allows_intentional_mixed_subject(draft: dict[str, Any]) -> bool:
    for event in draft.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        gate = event.get("multi_person_clip_gate") if isinstance(event.get("multi_person_clip_gate"), dict) else None
        if gate and gate.get("decision") == "allowed_social_moment":
            return True
    return False


__all__ = [
    "MIXED_SUBJECT_DEFECT",
    "annotate_mixed_subject_events",
    "draft_allows_intentional_mixed_subject",
    "draft_blocks_mixed_subject",
    "summarize_event_subjects",
]

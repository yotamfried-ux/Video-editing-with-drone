"""Same-window multi-person gate for REAL-ID-004.

This gate can consume explicit event metadata or derive visible canonical tracks
from the production perception sidecar. If a single-athlete draft window has no
primary track dominance and the event is not explicitly a social moment, the
draft must be review-required instead of looking like a normal approve.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Any

MULTI_PERSON_DEFECT = "MULTI_PERSON_CLIP"
IDENTITY_UNCERTAIN_DEFECT = "IDENTITY_UNCERTAIN"
_SOCIAL_LABELS = {"SOCIAL_MOMENT", "HIGH_FIVE"}
_SOCIAL_TYPES = {"high_five", "celebration", "team_interaction"}
_ID_FIELDS = (
    "visible_track_ids",
    "nearby_track_ids",
    "source_window_track_ids",
    "all_visible_track_ids",
    "visible_person_ids",
    "nearby_person_ids",
    "source_window_person_ids",
    "all_visible_person_ids",
)
_OTHER_FIELDS = ("other_track_ids", "other_person_ids", "secondary_track_ids", "secondary_person_ids")
_MIXED_SUBJECT_MIN_DETECTIONS = 4
_MIXED_SUBJECT_MIN_TRACKS = 2
_MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE = 0.7


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = [value]
    return [str(item).strip() for item in raw if str(item).strip()]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _event_source(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def _event_window(event: dict[str, Any]) -> tuple[float, float] | None:
    start = _num(event.get("start"), float("nan"))
    end = _num(event.get("end"), float("nan"))
    if start != start or end != end or end <= start:
        return None
    return start, end


def _primary_subject_id(event: dict[str, Any]) -> str:
    for key in ("track_id", "athlete_id", "person_id"):
        value = str(event.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    mixed = event.get("mixed_subject_source_gate") if isinstance(event.get("mixed_subject_source_gate"), dict) else {}
    primary = str(mixed.get("primary_track_id") or "").strip()
    if primary:
        return f"track_id:{primary}"
    return "unknown"


def _visible_subject_ids(event: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    primary = _primary_subject_id(event)
    if primary != "unknown":
        ids.add(primary)
    for key in _ID_FIELDS:
        prefix = "track_id" if "track" in key else "person_id"
        ids.update(f"{prefix}:{value}" for value in _as_list(event.get(key)))
    for key in _OTHER_FIELDS:
        prefix = "track_id" if "track" in key else "person_id"
        values = _as_list(event.get(key))
        if values and primary != "unknown":
            ids.add(primary)
        ids.update(f"{prefix}:{value}" for value in values)
    return sorted(ids)


def _value_labels(event: dict[str, Any]) -> set[str]:
    return {str(label).upper() for label in _as_list(event.get("value_labels"))}


def is_intentional_social_moment(event: dict[str, Any]) -> bool:
    if bool(event.get("allow_multi_person") or event.get("intentional_multi_person")):
        return True
    labels = _value_labels(event)
    if labels & _SOCIAL_LABELS:
        return True
    event_type = str(event.get("type") or "").lower().replace("-", "_").replace(" ", "_")
    if event_type in _SOCIAL_TYPES:
        return True
    description = str(event.get("description") or "").lower()
    return "high five" in description or "high-five" in description


@lru_cache(maxsize=16)
def _sidecar_detection_records(source: str) -> tuple[dict[str, Any], ...]:
    if not source:
        return tuple()
    try:
        from pipeline.perception.runtime import load_sidecar_detections
        detections = load_sidecar_detections(source)
    except Exception:
        return tuple()
    records: list[dict[str, Any]] = []
    for detection in detections:
        tracker_id = getattr(detection, "tracker_id", None)
        if tracker_id is None:
            continue
        records.append({
            "time_sec": float(getattr(detection, "time_sec", 0.0)),
            "track_id": str(tracker_id),
            "confidence": getattr(detection, "confidence", None),
        })
    return tuple(records)


def _source_track_counts(event: dict[str, Any]) -> Counter[str]:
    source = _event_source(event)
    window = _event_window(event)
    if not source or not window:
        return Counter()
    start, end = window
    counts: Counter[str] = Counter()
    for detection in _sidecar_detection_records(source):
        time_sec = _num(detection.get("time_sec"))
        if start <= time_sec <= end:
            counts[str(detection["track_id"])] += 1
    return counts


def build_mixed_subject_source_gate(event: dict[str, Any]) -> dict[str, Any] | None:
    counts = _source_track_counts(event)
    total = sum(counts.values())
    if total < _MIXED_SUBJECT_MIN_DETECTIONS or len(counts) < _MIXED_SUBJECT_MIN_TRACKS:
        return None
    primary_track, primary_count = counts.most_common(1)[0]
    dominance = primary_count / total if total else 0.0
    decision = "review_required" if dominance <= _MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE else "allowed_primary_dominant"
    return {
        "decision": decision,
        "reason": "low_primary_track_dominance" if decision == "review_required" else "primary_track_dominant",
        "source_video": _event_source(event),
        "source_window": {"start": event.get("start"), "end": event.get("end")},
        "detection_count": total,
        "visible_track_count": len(counts),
        "visible_track_ids": sorted(counts.keys()),
        "track_detection_counts": dict(sorted(counts.items())),
        "primary_track_id": primary_track,
        "primary_track_detections": primary_count,
        "primary_track_dominance_ratio": round(dominance, 3),
        "thresholds": {
            "min_detections": _MIXED_SUBJECT_MIN_DETECTIONS,
            "min_tracks": _MIXED_SUBJECT_MIN_TRACKS,
            "max_primary_dominance": _MIXED_SUBJECT_MAX_PRIMARY_DOMINANCE,
        },
    }


def _enrich_event_from_sidecar(event: dict[str, Any]) -> dict[str, Any]:
    if any(_as_list(event.get(key)) for key in _ID_FIELDS):
        return event
    gate = build_mixed_subject_source_gate(event)
    if not gate:
        return event
    enriched = {
        **event,
        "mixed_subject_source_gate": gate,
        "primary_track_id": gate.get("primary_track_id"),
        "primary_track_dominance_ratio": gate.get("primary_track_dominance_ratio"),
        "track_detection_counts": gate.get("track_detection_counts", {}),
    }
    if gate.get("decision") == "review_required":
        # Expose only low-dominance mixed windows through the existing visible-id
        # fields. Dominant-primary windows remain diagnostic only and do not block.
        enriched.update({
            "source_window_track_ids": gate.get("visible_track_ids", []),
            "visible_track_ids": gate.get("visible_track_ids", []),
            "all_visible_track_ids": gate.get("visible_track_ids", []),
        })
    return enriched


def build_multi_person_gate(event: dict[str, Any], index: int) -> dict[str, Any]:
    visible_ids = _visible_subject_ids(event)
    primary_id = _primary_subject_id(event)
    social = is_intentional_social_moment(event)
    mixed_gate = event.get("mixed_subject_source_gate") if isinstance(event.get("mixed_subject_source_gate"), dict) else {}
    decision = "allowed_social_moment" if social else "review_required"
    reason = "intentional_social_moment" if social else str(mixed_gate.get("reason") or "extra_visible_subject_in_single_athlete_draft")
    gate = {
        "decision": decision,
        "reason": reason,
        "event_id": _event_id(event, index),
        "primary_subject_id": primary_id,
        "visible_subject_ids": visible_ids,
        "visible_subject_count": len(visible_ids),
        "intentional_social_moment": social,
        "mixed_subject_source_gate": mixed_gate,
    }
    if not social:
        dominance = mixed_gate.get("primary_track_dominance_ratio")
        note = "single-athlete draft window contains another visible subject without SOCIAL_MOMENT evidence"
        if dominance is not None:
            note = f"single-athlete draft window has low primary-track dominance ({dominance})"
        gate["defect"] = {
            "type": MULTI_PERSON_DEFECT,
            "severity": "critical",
            "blocking": True,
            "event_id": gate["event_id"],
            "note": note,
            "primary_subject_id": primary_id,
            "visible_subject_ids": visible_ids,
            "primary_track_dominance_ratio": dominance,
        }
    return gate


def _merge_qa_gate(event: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    defect = gate.get("defect")
    if not defect:
        return event
    qa_gate = dict(event.get("qa_gate") or {})
    defects = [*qa_gate.get("defects", [])]
    defects.append(defect)
    qa_gate.update({
        "decision": qa_gate.get("decision") or "review_required_multi_person",
        "final_verdict": "FAIL",
        "qa_review_required": True,
        "critical_defect_count": max(1, int(qa_gate.get("critical_defect_count") or 0) + 1),
        "defects": defects,
        "overall": qa_gate.get("overall") or "multi-person source window requires operator review",
    })
    return {**event, "qa_gate": qa_gate}


def annotate_multi_person_events(events: list[dict[str, Any]], athlete_label: str = "") -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for index, event in enumerate(events or []):
        if not isinstance(event, dict):
            annotated.append(event)
            continue
        event = _enrich_event_from_sidecar(event)
        visible_ids = _visible_subject_ids(event)
        if len(visible_ids) <= 1:
            annotated.append(event)
            continue
        gate = build_multi_person_gate(event, index)
        next_event = {**event, "multi_person_clip_gate": gate}
        next_event = _merge_qa_gate(next_event, gate)
        annotated.append(next_event)
    return annotated


def has_multi_person_defect(events: list[dict[str, Any]]) -> bool:
    for event in events or []:
        gate = event.get("multi_person_clip_gate") if isinstance(event, dict) else None
        if isinstance(gate, dict) and gate.get("decision") == "review_required":
            return True
    return False

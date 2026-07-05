"""Same-window multi-person gate for REAL-ID-004.

This gate does not try to detect people by itself. It consumes tracker/perception
metadata when present and fails safe: if a single-athlete draft window has more
than one visible subject and the event is not explicitly a social moment, the
resulting draft must be review-required instead of looking like a normal approve.
"""
from __future__ import annotations

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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = [value]
    return [str(item).strip() for item in raw if str(item).strip()]


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _primary_subject_id(event: dict[str, Any]) -> str:
    for key in ("track_id", "athlete_id", "person_id"):
        value = str(event.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
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


def build_multi_person_gate(event: dict[str, Any], index: int) -> dict[str, Any]:
    visible_ids = _visible_subject_ids(event)
    primary_id = _primary_subject_id(event)
    social = is_intentional_social_moment(event)
    decision = "allowed_social_moment" if social else "review_required"
    reason = "intentional_social_moment" if social else "extra_visible_subject_in_single_athlete_draft"
    gate = {
        "decision": decision,
        "reason": reason,
        "event_id": _event_id(event, index),
        "primary_subject_id": primary_id,
        "visible_subject_ids": visible_ids,
        "visible_subject_count": len(visible_ids),
        "intentional_social_moment": social,
    }
    if not social:
        gate["defect"] = {
            "type": MULTI_PERSON_DEFECT,
            "severity": "critical",
            "blocking": True,
            "event_id": gate["event_id"],
            "note": "single-athlete draft window contains another visible subject without SOCIAL_MOMENT evidence",
            "primary_subject_id": primary_id,
            "visible_subject_ids": visible_ids,
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

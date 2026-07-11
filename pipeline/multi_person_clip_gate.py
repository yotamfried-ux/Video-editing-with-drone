"""Primary-actor gate for events containing multiple visible people.

Extra people are normal in most sports. This gate blocks only when the athlete
performing the highlighted action cannot be followed reliably, identity switches,
or the key action is materially obscured.
"""
from __future__ import annotations

from typing import Any

from pipeline.primary_actor_policy import classify_primary_actor

MULTI_PERSON_DEFECT = "MULTI_PERSON_CLIP"
IDENTITY_UNCERTAIN_DEFECT = "IDENTITY_UNCERTAIN"
ALLOWED_PRIMARY_ACTOR_DECISION = "allowed_primary_actor_clear"
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
    raw = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in raw if str(item).strip()]


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _primary_subject_id(event: dict[str, Any]) -> str:
    for key in ("target_track_id", "primary_track_id", "athlete_track_id", "track_id", "athlete_id", "person_id"):
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
        ids.update(f"{prefix}:{value}" for value in _as_list(event.get(key)))
    return sorted(ids)


def _value_labels(event: dict[str, Any]) -> set[str]:
    return {str(label).upper() for label in _as_list(event.get("value_labels"))}


def is_intentional_social_moment(event: dict[str, Any]) -> bool:
    if bool(event.get("allow_multi_person") or event.get("intentional_multi_person")):
        return True
    if _value_labels(event) & _SOCIAL_LABELS:
        return True
    event_type = str(event.get("type") or "").lower().replace("-", "_").replace(" ", "_")
    if event_type in _SOCIAL_TYPES:
        return True
    description = str(event.get("description") or "").lower()
    return "high five" in description or "high-five" in description


def build_multi_person_gate(event: dict[str, Any], index: int) -> dict[str, Any]:
    visible_ids = _visible_subject_ids(event)
    social = is_intentional_social_moment(event)
    if social:
        return {
            "decision": "allowed_social_moment",
            "reason": "intentional_social_moment",
            "event_id": _event_id(event, index),
            "primary_subject_id": _primary_subject_id(event),
            "visible_subject_ids": visible_ids,
            "visible_subject_count": len(visible_ids),
            "intentional_social_moment": True,
            "background_people_allowed": True,
        }

    classification = classify_primary_actor(event, visible_subject_count=len(visible_ids))
    gate = {
        **classification,
        "event_id": _event_id(event, index),
        "primary_subject_id": _primary_subject_id(event),
        "visible_subject_ids": visible_ids,
        "intentional_social_moment": False,
    }
    if classification.get("decision") == ALLOWED_PRIMARY_ACTOR_DECISION:
        gate["background_people_allowed"] = len(visible_ids) > 1
    if classification.get("decision") == "review_required":
        defect_type = str(classification.get("defect_type") or IDENTITY_UNCERTAIN_DEFECT)
        gate["defect"] = {
            "type": defect_type,
            "severity": "critical",
            "blocking": True,
            "event_id": gate["event_id"],
            "note": "primary athlete cannot be followed reliably through the highlighted action",
            "primary_subject_id": gate["primary_subject_id"],
            "visible_subject_ids": visible_ids,
            "ambiguity_reasons": classification.get("ambiguity_reasons", []),
        }
    return gate


def _merge_qa_gate(event: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    defect = gate.get("defect")
    if not defect:
        return event
    qa_gate = dict(event.get("qa_gate") or {})
    defects = [*qa_gate.get("defects", []), defect]
    reason_code = str(defect.get("type") or IDENTITY_UNCERTAIN_DEFECT)
    reasons = [*qa_gate.get("review_required_reasons", [])]
    if reason_code not in reasons:
        reasons.append(reason_code)
    blocked = [*qa_gate.get("approval_blocked_reasons", [])]
    block_reason = f"{reason_code}: {defect.get('note')}"
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
        "overall": qa_gate.get("overall") or "primary athlete is not reliably attributable",
    })
    return {**event, "qa_gate": qa_gate}


def annotate_multi_person_events(events: list[dict[str, Any]], athlete_label: str = "") -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for index, event in enumerate(events or []):
        if not isinstance(event, dict):
            annotated.append(event)
            continue
        visible_ids = _visible_subject_ids(event)
        if len(visible_ids) <= 1 and not event.get("primary_actor_clear") is False:
            annotated.append(event)
            continue
        gate = build_multi_person_gate(event, index)
        next_event = {**event, "multi_person_clip_gate": gate}
        annotated.append(_merge_qa_gate(next_event, gate))
    return annotated


def has_multi_person_defect(events: list[dict[str, Any]]) -> bool:
    for event in events or []:
        gate = event.get("multi_person_clip_gate") if isinstance(event, dict) else None
        if isinstance(gate, dict) and gate.get("decision") == "review_required":
            return True
    return False

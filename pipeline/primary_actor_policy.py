"""Sport-agnostic primary-actor continuity policy.

People in the background are normal in surfing, football, basketball, cycling,
and most other sports. A clip is unsafe only when the athlete performing the
highlight cannot be followed reliably through the action.
"""
from __future__ import annotations

from typing import Any

PRIMARY_ACTOR_UNCLEAR = "PRIMARY_ACTOR_UNCLEAR"
IDENTITY_SWITCH = "IDENTITY_SWITCH"
PRIMARY_ACTOR_OCCLUDED = "PRIMARY_ACTOR_OCCLUDED"
MIN_PRIMARY_ACTOR_CONFIDENCE = 0.55
FOCUSED_SUBWINDOW_SCOPE = "focused_subwindow"

_BAD_STATUS_VALUES = {
    "ambiguous",
    "unclear",
    "unknown",
    "lost",
    "switched",
    "identity_switch",
    "target_lost",
    "occluded",
    "blocked",
}

_TRUE_AMBIGUITY_FIELDS = (
    "primary_actor_unclear",
    "actor_ambiguous",
    "identity_switch",
    "identity_switch_detected",
    "target_lost",
    "primary_actor_lost",
    "target_occluded_at_key_moment",
    "primary_actor_occluded_at_key_moment",
    "critical_occlusion",
    "multiple_active_subjects",
    "competing_active_subjects",
    "competing_primary_actors",
)


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "yes", "1"}:
            return True
        if value in {"false", "no", "0"}:
            return False
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def primary_actor_id(event: dict[str, Any]) -> str | None:
    for key in (
        "target_track_id",
        "primary_track_id",
        "athlete_track_id",
        "track_id",
        "athlete_id",
        "person_id",
    ):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def primary_actor_confidence(event: dict[str, Any]) -> float | None:
    for key in ("primary_actor_confidence", "identity_confidence", "target_confidence"):
        value = _float(event.get(key))
        if value is not None:
            return max(0.0, min(1.0, value))
    return None


def explicit_primary_actor_clear(event: dict[str, Any]) -> bool | None:
    for key in ("primary_actor_clear", "target_actor_clear", "main_athlete_clear"):
        value = _bool(event.get(key))
        if value is not None:
            return value
    return None


def normalize_focused_subwindow_evidence(event: dict[str, Any]) -> dict[str, Any]:
    """Clear broad-window ambiguity flags after selecting a focused sub-window.

    The original evidence is retained for audit, but downstream gates evaluate the
    focused window rather than stale identity/occlusion flags from the wider event.
    Sidecar continuity and explicit target-presence checks still run afterwards.
    """
    normalized = dict(event)
    normalized["broad_window_ambiguity_reasons"] = ambiguity_reasons(event)
    for key in _TRUE_AMBIGUITY_FIELDS:
        normalized[key] = False
    normalized.update({
        "primary_actor_clear": True,
        "target_actor_clear": True,
        "main_athlete_clear": True,
        "identity_continuity": "stable",
        "primary_actor_status": "stable",
        "actor_tracking_status": "stable",
        "competing_active_subjects": False,
        "target_occluded_at_key_moment": False,
        "primary_actor_evidence_scope": FOCUSED_SUBWINDOW_SCOPE,
    })
    confidence = primary_actor_confidence(event)
    normalized["primary_actor_confidence"] = max(0.75, confidence or 0.0)
    return normalized


def ambiguity_reasons(event: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in _TRUE_AMBIGUITY_FIELDS:
        if _bool(event.get(key)) is True:
            reasons.append(key)

    for key in ("primary_actor_status", "identity_continuity", "actor_tracking_status"):
        value = str(event.get(key) or "").strip().lower().replace("-", "_").replace(" ", "_")
        if value in _BAD_STATUS_VALUES:
            reasons.append(f"{key}:{value}")

    clear = explicit_primary_actor_clear(event)
    if clear is False:
        reasons.append("primary_actor_clear:false")

    confidence = primary_actor_confidence(event)
    if confidence is not None and confidence < MIN_PRIMARY_ACTOR_CONFIDENCE:
        reasons.append(f"primary_actor_confidence:{confidence:.3f}")

    # A focused sub-window has new scoped evidence. Do not reapply natural-language
    # ambiguity phrases describing the wider event; deterministic sidecar gates still
    # verify target presence and continuity in the focused cut itself.
    if event.get("primary_actor_evidence_scope") != FOCUSED_SUBWINDOW_SCOPE:
        text = f"{event.get('description', '')} {event.get('notes', '')}".lower()
        phrases = {
            "identity switches": "identity_switch_description",
            "switches to another player": "identity_switch_description",
            "switches to another athlete": "identity_switch_description",
            "loses track of the target": "target_lost_description",
            "primary athlete is unclear": "primary_actor_unclear_description",
            "target is obscured at the key moment": "primary_actor_occluded_description",
            "cannot tell which player": "primary_actor_unclear_description",
        }
        for phrase, code in phrases.items():
            if phrase in text:
                reasons.append(code)

    return list(dict.fromkeys(reasons))


def blocking_defect_type(reasons: list[str]) -> str:
    joined = " ".join(reasons)
    if "switch" in joined:
        return IDENTITY_SWITCH
    if "occlu" in joined:
        return PRIMARY_ACTOR_OCCLUDED
    return PRIMARY_ACTOR_UNCLEAR


def classify_primary_actor(
    event: dict[str, Any],
    *,
    visible_subject_count: int = 0,
    primary_continuity_ratio: float | None = None,
) -> dict[str, Any]:
    """Classify whether the athlete performing the action remains followable.

    Additional visible people are explicitly non-blocking. The decision only
    becomes review-required when identity/action attribution is uncertain.
    """
    reasons = ambiguity_reasons(event)
    actor_id = primary_actor_id(event)
    clear = explicit_primary_actor_clear(event)
    confidence = primary_actor_confidence(event)

    if primary_continuity_ratio is not None and primary_continuity_ratio < 0.50:
        reasons.append(f"primary_continuity_ratio:{primary_continuity_ratio:.3f}")

    if reasons:
        defect_type = blocking_defect_type(reasons)
        return {
            "decision": "review_required",
            "reason": "primary_actor_not_reliably_followable",
            "defect_type": defect_type,
            "primary_actor_id": actor_id,
            "primary_actor_clear": clear,
            "primary_actor_confidence": confidence,
            "primary_continuity_ratio": primary_continuity_ratio,
            "visible_subject_count": visible_subject_count,
            "background_people_allowed": False,
            "ambiguity_reasons": list(dict.fromkeys(reasons)),
        }

    if actor_id or clear is True or (primary_continuity_ratio is not None and primary_continuity_ratio >= 0.50):
        return {
            "decision": "allowed_primary_actor_clear",
            "reason": "primary_actor_continuous_background_people_allowed",
            "primary_actor_id": actor_id,
            "primary_actor_clear": clear,
            "primary_actor_confidence": confidence,
            "primary_continuity_ratio": primary_continuity_ratio,
            "visible_subject_count": visible_subject_count,
            "background_people_allowed": visible_subject_count > 1,
            "ambiguity_reasons": [],
        }

    if visible_subject_count <= 1:
        return {
            "decision": "allowed_single_visible_subject",
            "reason": "single_visible_subject",
            "primary_actor_id": actor_id,
            "visible_subject_count": visible_subject_count,
            "background_people_allowed": False,
            "ambiguity_reasons": [],
        }

    return {
        "decision": "review_required",
        "reason": "primary_actor_unknown_among_multiple_visible_subjects",
        "defect_type": PRIMARY_ACTOR_UNCLEAR,
        "primary_actor_id": None,
        "visible_subject_count": visible_subject_count,
        "background_people_allowed": False,
        "ambiguity_reasons": ["primary_actor_unknown"],
    }

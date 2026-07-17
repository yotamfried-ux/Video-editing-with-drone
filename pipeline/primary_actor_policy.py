"""Sport-agnostic primary-athlete continuity policy.

A personal reel is centered on one target athlete; it does not require an empty
frame or a solo action. Teammates, opponents, officials, bystanders, and even
another surfer on the same wave are allowed when the target athlete remains the
clear, continuous subject and the featured action is attributable to them.
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

_STABLE_STATUS_VALUES = {
    "clear",
    "continuous",
    "followed",
    "stable",
    "tracked",
}

# These are true identity/continuity failures and remain blocking regardless of
# how many other people are visible.
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
)

# Active people around the target are context, not an automatic identity defect.
# They become blocking only when the target athlete is not clearly attributable.
_ACTIVE_CONTEXT_FIELDS = (
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


def _status(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


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


def _identity_statuses(event: dict[str, Any]) -> list[str]:
    return [
        _status(event.get(key))
        for key in ("primary_actor_status", "identity_continuity", "actor_tracking_status")
        if _status(event.get(key))
    ]


def _target_is_clearly_centered(event: dict[str, Any]) -> bool:
    """Return true when other active people do not obscure action ownership."""
    clear = explicit_primary_actor_clear(event)
    confidence = primary_actor_confidence(event)
    statuses = _identity_statuses(event)
    has_bad_status = any(value in _BAD_STATUS_VALUES for value in statuses)
    stable_status = not statuses or any(value in _STABLE_STATUS_VALUES for value in statuses)
    confidence_ok = confidence is None or confidence >= MIN_PRIMARY_ACTOR_CONFIDENCE
    has_identity = primary_actor_id(event) is not None
    return not has_bad_status and confidence_ok and (
        clear is True or (has_identity and stable_status)
    )


def normalize_focused_subwindow_evidence(event: dict[str, Any]) -> dict[str, Any]:
    """Clear broad-window ambiguity flags after selecting a focused sub-window.

    The original evidence is retained for audit, but downstream gates evaluate the
    focused window rather than stale identity/occlusion flags from the wider event.
    Sidecar continuity and explicit target-presence checks still run afterwards.
    """
    normalized = dict(event)
    normalized["broad_window_ambiguity_reasons"] = ambiguity_reasons(event)
    for key in (*_TRUE_AMBIGUITY_FIELDS, *_ACTIVE_CONTEXT_FIELDS):
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
        value = _status(event.get(key))
        if value in _BAD_STATUS_VALUES:
            reasons.append(f"{key}:{value}")

    clear = explicit_primary_actor_clear(event)
    if clear is False:
        reasons.append("primary_actor_clear:false")

    confidence = primary_actor_confidence(event)
    if confidence is not None and confidence < MIN_PRIMARY_ACTOR_CONFIDENCE:
        reasons.append(f"primary_actor_confidence:{confidence:.3f}")

    # Multiple people may all be actively participating in the same play or wave.
    # Do not convert that normal sports context into a mixed-athlete defect when the
    # target remains centered, trackable, and clearly owns the featured action.
    if not _target_is_clearly_centered(event):
        for key in _ACTIVE_CONTEXT_FIELDS:
            if _bool(event.get(key)) is True:
                reasons.append(key)

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
    """Classify whether the featured athlete remains centered and followable.

    Additional visible or active people are explicitly non-blocking. The decision
    becomes review-required only when identity, continuity, or action attribution
    to the featured athlete is uncertain.
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
            "primary_athlete_centered": False,
            "other_people_allowed": False,
            "background_people_allowed": False,
            "ambiguity_reasons": list(dict.fromkeys(reasons)),
        }

    if actor_id or clear is True or (primary_continuity_ratio is not None and primary_continuity_ratio >= 0.50):
        return {
            "decision": "allowed_primary_actor_clear",
            "reason": "primary_athlete_centered_other_people_allowed",
            "primary_actor_id": actor_id,
            "primary_actor_clear": clear,
            "primary_actor_confidence": confidence,
            "primary_continuity_ratio": primary_continuity_ratio,
            "visible_subject_count": visible_subject_count,
            "primary_athlete_centered": True,
            "other_people_allowed": visible_subject_count > 1,
            "background_people_allowed": visible_subject_count > 1,
            "ambiguity_reasons": [],
        }

    if visible_subject_count <= 1:
        return {
            "decision": "allowed_single_visible_subject",
            "reason": "single_visible_subject",
            "primary_actor_id": actor_id,
            "visible_subject_count": visible_subject_count,
            "primary_athlete_centered": True,
            "other_people_allowed": False,
            "background_people_allowed": False,
            "ambiguity_reasons": [],
        }

    return {
        "decision": "review_required",
        "reason": "primary_actor_unknown_among_multiple_visible_subjects",
        "defect_type": PRIMARY_ACTOR_UNCLEAR,
        "primary_actor_id": None,
        "visible_subject_count": visible_subject_count,
        "primary_athlete_centered": False,
        "other_people_allowed": False,
        "background_people_allowed": False,
        "ambiguity_reasons": ["primary_actor_unknown"],
    }


def merge_gate_defect_into_qa(
    event: dict[str, Any],
    gate: dict[str, Any],
    *,
    default_defect_type: str,
    overall_fallback: str,
) -> dict[str, Any]:
    """Merge one blocking actor-gate defect into the event QA payload.

    Both native-video and sidecar continuity gates use this path so their persisted
    block reasons and QA state cannot drift apart.
    """
    defect = gate.get("defect")
    if not isinstance(defect, dict):
        return event
    qa_gate = dict(event.get("qa_gate") or {})
    defects = [*qa_gate.get("defects", []), defect]
    reason_code = str(defect.get("type") or default_defect_type)
    reasons = [*qa_gate.get("review_required_reasons", [])]
    if reason_code not in reasons:
        reasons.append(reason_code)
    blocked = [*qa_gate.get("approval_blocked_reasons", [])]
    note = str(defect.get("note") or "").strip()
    block_reason = f"{reason_code}: {note}" if note else reason_code
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
        "overall": qa_gate.get("overall") or overall_fallback,
    })
    return {**event, "qa_gate": qa_gate}

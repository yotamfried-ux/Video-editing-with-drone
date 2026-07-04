"""Narrative quality policy for PQ-008."""
from __future__ import annotations

from typing import Any

MIN_CLIMAX_QUALITY = 6.5
MIN_VISIBLE_RATIO = 0.35


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _identity_ok(event: dict[str, Any]) -> bool:
    if event.get("identity_mismatch") is True or event.get("mixed_athlete") is True:
        return False
    confidence = str(event.get("identity_confidence", "medium")).lower()
    return confidence not in {"low", "none", "unknown"}


def has_quality_evidence(event: dict[str, Any]) -> bool:
    visible = _num(event.get("visible_ratio"), 1.0)
    perception = _num(event.get("perception_confidence"), _num(event.get("confidence"), 1.0))
    window_status = str(event.get("window_validation_status", "valid")).lower()
    if visible < MIN_VISIBLE_RATIO:
        return False
    if perception < 0.25:
        return False
    if window_status in {"rejected", "manual_review"}:
        return False
    if not _identity_ok(event):
        return False
    return True


def quality_score(event: dict[str, Any]) -> float:
    score = _num(event.get("score"), 0.0)
    visible = max(0.0, min(1.0, _num(event.get("visible_ratio"), 1.0)))
    perception = max(0.0, min(1.0, _num(event.get("perception_confidence"), _num(event.get("confidence"), 1.0))))
    track_bonus = 0.6 if event.get("track_id") is not None or event.get("track_continuity") else 0.0
    action_bonus = 0.6 if event.get("peak_time") is not None or event.get("action_time") is not None else 0.0
    window_bonus = 0.4 if str(event.get("window_validation_status", "valid")).lower() in {"valid", "adjusted"} else -2.0
    identity_bonus = 0.4 if _identity_ok(event) else -3.0
    evidence_penalty = 0.0 if has_quality_evidence(event) else -3.0
    return score * 0.6 + visible * 1.6 + perception * 1.0 + track_bonus + action_bonus + window_bonus + identity_bonus + evidence_penalty


def choose_climax(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    qualified = [event for event in events if has_quality_evidence(event) and quality_score(event) >= MIN_CLIMAX_QUALITY]
    if not qualified:
        return None
    return max(qualified, key=quality_score)


def order_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(events) <= 1:
        return list(events)
    climax = choose_climax(events)
    if climax is None:
        return sorted(events, key=quality_score)
    rest = [event for event in events if event is not climax]
    rest_desc = sorted(rest, key=quality_score, reverse=True)
    opener = rest_desc[0] if rest_desc else None
    middle = sorted(rest_desc[1:], key=quality_score)
    return ([opener] if opener else []) + middle + [climax]


def install() -> None:
    import pipeline.stages.editor as editor

    flag = "_sportreel_narrative_policy_installed"
    if getattr(editor, flag, False):
        return

    original_cut_clip = editor.cut_clip

    def cut_clip_without_unqualified_teaser(video_path, event, index, slowmo=False, sport="", source_info=None, session_peak=10, target_fps=None):
        if event.get("_teaser") is True and event.get("_disable_teaser") is True:
            return None
        return original_cut_clip(video_path, event, index, slowmo, sport, source_info, session_peak, target_fps)

    def patched_narrative_order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = order_events(events)
        if not ordered:
            return ordered
        if choose_climax(events) is None:
            no_teaser = [
                {**event, "_disable_teaser": True, "_is_climax": False, "edit": {**(event.get("edit") or {}), "slowmo": False}}
                for event in ordered
            ]
            return no_teaser
        return editor._enforce_single_slowmo(editor._break_slowmo_runs(ordered))

    editor.cut_clip = cut_clip_without_unqualified_teaser
    editor._narrative_order = patched_narrative_order
    setattr(editor, flag, True)

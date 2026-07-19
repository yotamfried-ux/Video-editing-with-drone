"""Prevent generic highlight pacing from truncating complete performance actions."""
from __future__ import annotations

from typing import Any

_INSTALLED_FLAG = "_sportreel_complete_action_window_policy_installed"


def _is_complete_performance_action(event: dict[str, Any]) -> bool:
    return str(event.get("performance_reel_contract") or "") == (
        "all_usable_waves_per_athlete_v1"
    )


def normalize_complete_action_event(event: dict[str, Any]) -> dict[str, Any]:
    """Persist the exact full action window used by the renderer and final QA.

    This normalization is intentionally applied both before cutting and when
    `_events_out` is built. A temporary cut wrapper alone is insufficient because
    identity/continuity gates later derive evidence from the persisted event.
    """
    effective = dict(event)
    if not _is_complete_performance_action(effective) or effective.get("_teaser"):
        return effective
    effective.pop("_cap_dur", None)
    effective.pop("_single_clip_cap", None)
    effective["_is_climax"] = True
    try:
        start = float(effective.get("start"))
        end = float(effective.get("end"))
    except (TypeError, ValueError):
        return effective
    if end < start:
        start, end = end, start
    effective["final_cut_start"] = round(start, 3)
    effective["final_cut_end"] = round(end, 3)
    effective["complete_action_window_preserved"] = True
    return effective


def install() -> None:
    """Remove historical pacing caps and persist the same complete action window."""
    from pipeline.stages import editor

    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original_cut_clip = editor.cut_clip
    original_rendered_timeline = getattr(editor, "_events_with_rendered_timeline", None)

    def cut_complete_action(
        video_path: str,
        event: dict[str, Any],
        index: int,
        slowmo: bool = False,
        sport: str = "",
        source_info: dict[str, Any] | None = None,
        session_peak: int = 10,
        target_fps: int | None = None,
    ):
        effective = normalize_complete_action_event(event)
        return original_cut_clip(
            video_path,
            effective,
            index,
            slowmo,
            sport,
            source_info,
            session_peak,
            target_fps,
        )

    editor.cut_clip = cut_complete_action
    if callable(original_rendered_timeline):
        def rendered_timeline_with_complete_actions(events, clip_paths, transitions=None):
            normalized = [
                normalize_complete_action_event(event)
                for event in list(events or [])
            ]
            return original_rendered_timeline(normalized, clip_paths, transitions)

        editor._events_with_rendered_timeline = rendered_timeline_with_complete_actions
    setattr(editor, _INSTALLED_FLAG, True)

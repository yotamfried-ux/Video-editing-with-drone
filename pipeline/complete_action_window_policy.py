"""Prevent generic highlight pacing from truncating complete performance actions."""
from __future__ import annotations

from typing import Any

_INSTALLED_FLAG = "_sportreel_complete_action_window_policy_installed"


def _is_complete_performance_action(event: dict[str, Any]) -> bool:
    return str(event.get("performance_reel_contract") or "") == (
        "all_usable_waves_per_athlete_v1"
    )


def install() -> None:
    """Remove the historical 15-second climax cap from complete surf rides."""
    from pipeline.stages import editor

    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original_cut_clip = editor.cut_clip

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
        effective = dict(event)
        if _is_complete_performance_action(effective):
            effective.pop("_cap_dur", None)
            # A whole ride is the performance unit. Treat it as climax-equivalent
            # for pacing so the generic non-climax MAX_NORMAL_WINDOW cap cannot
            # remove its setup or natural finish.
            effective["_is_climax"] = True
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
    setattr(editor, _INSTALLED_FLAG, True)

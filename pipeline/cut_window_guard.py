"""Real-output cut window guard for surf/wave outcome preservation."""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_cut_window_guard_installed"
TAIL_PADDING_SEC = 3.0
MAX_EXTENSION_SEC = 4.0
SURF_TERMS = {"surf", "surfing", "surfer", "wave", "longboard", "shortboard", "paddle", "cutback", "carve", "snap", "ride"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_time(event: dict[str, Any], *names: str) -> bool:
    return any(event.get(name) is not None for name in names)


def _is_surf_event(event: dict[str, Any], sport: str = "") -> bool:
    text = " ".join([sport, str(event.get("sport", "")), str(event.get("type", "")), str(event.get("description", ""))]).lower()
    return any(term in text for term in SURF_TERMS)


def needs_cut_window_guard(event: dict[str, Any], sport: str = "") -> bool:
    if event.get("_teaser") is True or event.get("empty_window") is True:
        return False
    if not _is_surf_event(event, sport):
        return False
    if _has_time(event, "outcome_end", "landing_time"):
        return False
    return True


def apply_cut_window_guard(event: dict[str, Any], source_duration: float, sport: str = "") -> dict[str, Any]:
    if not needs_cut_window_guard(event, sport):
        return event
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    if end <= start:
        return event
    padded_end = min(source_duration, end + min(TAIL_PADDING_SEC, MAX_EXTENSION_SEC))
    if padded_end <= end:
        return {**event, "cut_window_evidence_status": "outcome_missing_no_tail_available", "window_uncertain": True}
    return {
        **event,
        "original_end_before_cut_guard": round(end, 2),
        "outcome_end": round(padded_end, 2),
        "cut_window_evidence_status": "inferred_tail_padding",
        "cut_window_guard_reason": "missing_outcome_evidence",
        "window_uncertain": True,
    }


def _patch_editor(editor: Any) -> None:
    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original = editor.cut_clip

    def cut_clip_with_guard(video_path, event, index, slowmo=False, sport="", source_info=None, session_peak=10, target_fps=None):
        try:
            event = apply_cut_window_guard(event, editor._get_duration(video_path), sport)
        except Exception:
            pass
        return original(video_path, event, index, slowmo, sport, source_info, session_peak, target_fps)

    editor.cut_clip = cut_clip_with_guard
    setattr(editor, _INSTALLED_FLAG, True)


def install() -> None:
    module = sys.modules.get("pipeline.stages.editor")
    if module is not None:
        _patch_editor(module)
        return
    import pipeline.stages.editor as editor
    _patch_editor(editor)

"""Guard clip windows against early outcome cuts."""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_cut_window_guard_installed"
TAIL_PAD = 3.0
TERMS = {"surf", "surfing", "surfer", "wave", "longboard", "cutback", "carve", "snap", "ride"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has(event: dict[str, Any], *names: str) -> bool:
    return any(event.get(name) is not None for name in names)


def _match(event: dict[str, Any], sport: str = "") -> bool:
    text = " ".join([sport, str(event.get("sport", "")), str(event.get("type", "")), str(event.get("description", ""))]).lower()
    return any(term in text for term in TERMS)


def needs_cut_window_guard(event: dict[str, Any], sport: str = "") -> bool:
    return not event.get("_teaser") and not _has(event, "outcome_end", "landing_time") and _match(event, sport)


def apply_cut_window_guard(event: dict[str, Any], source_duration: float, sport: str = "") -> dict[str, Any]:
    if not needs_cut_window_guard(event, sport):
        return event
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    if end <= start:
        return event
    guarded_end = min(source_duration, end + TAIL_PAD)
    if guarded_end <= end:
        return {**event, "cut_window_evidence_status": "outcome_missing_no_tail_available", "window_uncertain": True}
    return {**event, "original_end_before_cut_guard": round(end, 2), "outcome_end": round(guarded_end, 2), "cut_window_evidence_status": "inferred_tail_padding", "cut_window_guard_reason": "missing_outcome_evidence", "window_uncertain": True}


def apply_to_appearances(appearances: list[dict[str, Any]], sport: str, duration_fn) -> list[dict[str, Any]]:
    out = []
    for app in appearances:
        path = app.get("path")
        try:
            duration = float(duration_fn(path)) if path else 0.0
        except Exception:
            out.append(app)
            continue
        events = [apply_cut_window_guard(event, duration, sport) for event in app.get("events", []) or []]
        out.append({**app, "events": events})
    return out


def _patch_editor(editor: Any) -> None:
    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original_cut = editor.cut_clip
    original_compile = editor.compile_multi_source_reel

    def cut_clip_guarded(video_path, event, index, slowmo=False, sport="", source_info=None, session_peak=10, target_fps=None):
        try:
            event = apply_cut_window_guard(event, editor._get_duration(video_path), sport)
        except Exception:
            pass
        return original_cut(video_path, event, index, slowmo, sport, source_info, session_peak, target_fps)

    def compile_guarded(appearances, sport="", athlete_label="", _events_out=None):
        guarded = apply_to_appearances(appearances, sport, editor._get_duration)
        return original_compile(guarded, sport, athlete_label, _events_out)

    editor.cut_clip = cut_clip_guarded
    editor.compile_multi_source_reel = compile_guarded
    setattr(editor, _INSTALLED_FLAG, True)


def install() -> None:
    module = sys.modules.get("pipeline.stages.editor")
    if module is not None:
        _patch_editor(module)
        return
    import pipeline.stages.editor as editor
    _patch_editor(editor)

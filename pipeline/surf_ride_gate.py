"""Runtime gate that makes surf rides atomic before editing."""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED = "_sportreel_surf_ride_gate_installed"


def _patch_editor(editor: Any) -> None:
    if getattr(editor, _INSTALLED, False):
        return
    from pipeline.surf_ride_segment import normalize_surf_rides
    original_create = editor.create_reel
    original_multi = editor.compile_multi_source_reel

    def create_reel_with_rides(video_path, events, sport="", athlete_label="", _events_out=None):
        rides = normalize_surf_rides(events, sport)
        return original_create(video_path, rides, sport, athlete_label, _events_out)

    def compile_multi_with_rides(appearances, sport="", athlete_label="", _events_out=None):
        guarded = []
        for app in appearances or []:
            events = [{**event, "_src": app.get("path")} for event in app.get("events", [])]
            rides = normalize_surf_rides(events, sport)
            guarded.append({**app, "events": rides})
        return original_multi(guarded, sport, athlete_label, _events_out)

    editor.create_reel = create_reel_with_rides
    editor.compile_multi_source_reel = compile_multi_with_rides
    setattr(editor, _INSTALLED, True)


def install() -> None:
    module = sys.modules.get("pipeline.stages.editor")
    if module is not None:
        _patch_editor(module)
        return
    import pipeline.stages.editor as editor
    _patch_editor(editor)

"""Runtime policy for teaser clips.

Cold-open teasers intentionally duplicate the climax inside the same reel, but in
multi-athlete surf footage the 2.5s teaser can also overlap another athlete's
full source window and create duplicate moments across REVIEW drafts. The product
priority is no repeated moments across drafts, so the tracked pipeline skips
teaser clips and removes them from per-draft decision metadata.
"""
from __future__ import annotations

from typing import Any

_INSTALLED_FLAG = "_sportreel_teaser_policy_installed"


def is_teaser_event(event: Any) -> bool:
    return isinstance(event, dict) and bool(event.get("_teaser"))


def strip_teaser_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if not is_teaser_event(event)]


def strip_teasers_from_events_out(events_out: list[tuple[str, list[dict[str, Any]]]], start_index: int = 0) -> None:
    for idx in range(start_index, len(events_out)):
        try:
            path, events = events_out[idx]
        except (TypeError, ValueError):
            continue
        if isinstance(events, list):
            events_out[idx] = (path, strip_teaser_events(events))


def install() -> None:
    import pipeline.stages.editor as editor

    if getattr(editor, _INSTALLED_FLAG, False):
        return

    original_cut_clip_with_qa = editor._cut_clip_with_qa
    original_create_reel = editor.create_reel
    original_compile_multi_source_reel = editor.compile_multi_source_reel

    def cut_clip_without_teaser(video_path, event, index, *args, **kwargs):
        if is_teaser_event(event):
            print("  ⏭️  Skipping cold-open teaser to avoid duplicate source moments across drafts")
            return None
        return original_cut_clip_with_qa(video_path, event, index, *args, **kwargs)

    def create_reel_without_teasers(video_path, events, sport="", athlete_label="", _events_out=None):
        start_index = len(_events_out) if isinstance(_events_out, list) else 0
        reels = original_create_reel(video_path, events, sport=sport, athlete_label=athlete_label, _events_out=_events_out)
        if isinstance(_events_out, list):
            strip_teasers_from_events_out(_events_out, start_index)
        return reels

    def compile_multi_source_reel_without_teasers(appearances, sport="", athlete_label="", _events_out=None):
        start_index = len(_events_out) if isinstance(_events_out, list) else 0
        reels = original_compile_multi_source_reel(appearances, sport=sport, athlete_label=athlete_label, _events_out=_events_out)
        if isinstance(_events_out, list):
            strip_teasers_from_events_out(_events_out, start_index)
        return reels

    editor._cut_clip_with_qa = cut_clip_without_teaser
    editor.create_reel = create_reel_without_teasers
    editor.compile_multi_source_reel = compile_multi_source_reel_without_teasers
    setattr(editor, _INSTALLED_FLAG, True)

"""Runtime support for repeated cross-source moments."""
from __future__ import annotations

from typing import Any

from pipeline.perception.event_fingerprint import deduplicate_cross_source_events

_INSTALLED_FLAG = "_sportreel_cross_source_dedup_installed"


def install() -> None:
    import pipeline.stages.editor as editor

    if getattr(editor, _INSTALLED_FLAG, False):
        return

    original_partition = editor._partition_events

    def partition_with_event_filter(
        events: list[dict[str, Any]],
        slowmo_capable: bool,
        target_max: float = editor.TARGET_REEL_MAX,
    ) -> list[list[dict[str, Any]]]:
        return original_partition(
            deduplicate_cross_source_events(events),
            slowmo_capable,
            target_max,
        )

    editor._partition_events = partition_with_event_filter
    setattr(editor, _INSTALLED_FLAG, True)

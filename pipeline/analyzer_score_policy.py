"""Analyzer-owned score policy for highlight candidates."""
from __future__ import annotations

from typing import Any

MIN_NORMAL_DRAFT_SCORE = 6


def qualifying_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only events allowed into a normal draft."""
    return sorted(
        [event for event in events if int(event.get("score", 0)) >= MIN_NORMAL_DRAFT_SCORE],
        key=lambda event: int(event.get("score", 0)),
        reverse=True,
    )

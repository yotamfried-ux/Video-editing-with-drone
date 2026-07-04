"""Analyzer-owned score policy for highlight candidates.

Gemini scores are advisory; production parser policy must not include weak
filler events just because a person has no score >= 6 moments.
"""
from __future__ import annotations

from typing import Any

MIN_NORMAL_DRAFT_SCORE = 6


def qualifying_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only events allowed into a normal draft.

    A score-5 moment may be useful for diagnostics or manual review later, but
    it is not allowed to become normal draft filler.
    """
    return sorted(
        [event for event in events if int(event.get("score", 0)) >= MIN_NORMAL_DRAFT_SCORE],
        key=lambda event: int(event.get("score", 0)),
        reverse=True,
    )

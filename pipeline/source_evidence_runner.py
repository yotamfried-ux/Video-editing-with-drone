"""Optional source-window evidence runner for reel QA."""
from __future__ import annotations

import os
from typing import Any

from pipeline.source_evidence import make_source_clips, source_evidence_prompt


def with_source_evidence(analyzer: Any, original, reel_path: str, *args, context: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    if not context:
        return original(reel_path, *args, **kwargs)
    clips = make_source_clips(context)
    if not clips:
        return original(reel_path, *args, **kwargs)
    try:
        label = str(kwargs.get("athlete_label", "")) + source_evidence_prompt(context)
        kwargs["athlete_label"] = label
        result = original(reel_path, *args, **kwargs)
        result["source_evidence_clip_count"] = len(clips)
        result["source_evidence_visual_uploaded"] = False
        return result
    finally:
        for clip in clips:
            try:
                os.remove(clip)
            except OSError:
                pass

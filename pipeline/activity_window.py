"""Activity window from the YOLO/tracker sidecar (the cheap "video analysis tool" for the LLM).

The sidecar already says when any person is in frame. Footage before the first and after the last
person detection cannot contain an athlete action, so the expensive LLM pass can skip it by sending
Gemini `start_offset`/`end_offset` (the timeline stays the source video's own, so no timestamp remap
is needed). Only the head/tail is trimmed — never an interior gap — and only when it saves enough.
"""
from __future__ import annotations

import os
from typing import Iterable

DEFAULT_PAD_SEC = 8.0
DEFAULT_MIN_SAVINGS = 0.20
MIN_DETECTIONS = 3


def enabled() -> bool:
    return os.getenv("ANALYSIS_TRIM_TO_ACTIVITY", "").strip().lower() in {"1", "true", "yes", "on"}


def compute_window(times: Iterable[float], duration: float, *, pad: float | None = None,
                   min_savings: float | None = None) -> tuple[float, float] | None:
    """(start, end) seconds to analyse, or None to analyse the whole video."""
    pad = DEFAULT_PAD_SEC if pad is None else pad
    min_savings = DEFAULT_MIN_SAVINGS if min_savings is None else min_savings
    stamps = sorted(float(t) for t in times if t is not None and 0.0 <= float(t) <= duration + 1.0)
    if duration <= 0 or len(stamps) < MIN_DETECTIONS:
        return None            # no/too little evidence → never trim on a guess
    start = max(0.0, stamps[0] - pad)
    end = min(duration, stamps[-1] + pad)
    if end - start >= duration * (1.0 - min_savings):
        return None
    return round(start, 1), round(end, 1)


def window_for_video(video_path: str, duration: float) -> tuple[float, float] | None:
    """Window from this video's perception sidecar; None when unavailable (fail-open)."""
    try:
        from pipeline.perception.runtime import load_sidecar_detections
        detections = load_sidecar_detections(video_path)
        return compute_window((d.time_sec for d in detections), duration)
    except Exception:
        return None

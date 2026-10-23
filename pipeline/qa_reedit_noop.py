"""Detect QA re-edits that cannot change the rendered reel.

A QA repair such as PREMATURE_CUT asks for 3 more seconds on a clip. When the clip's window already
reaches the end of its source file the editor clamps the extension away, so the re-render comes out
identical (run 39726001357: 5 of 10 re-edit renders had the same duration and size as the render
before) and costs a full render plus a QA call. Comparing the effective windows before rendering
lets the loop stop instead.
"""
from __future__ import annotations

import os
from typing import Any, Callable

WINDOW_TOLERANCE_SEC = 0.05


def enabled() -> bool:
    return os.getenv("QA_SKIP_NOOP_REEDIT", "1").strip().lower() not in {"0", "false", "no", "off"}


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _effective_window(event: dict[str, Any], duration_fn: Callable[[str], float]) -> tuple[float, float] | None:
    # Requested start/end only: `final_cut_*` is copied unchanged from the rendered event into the
    # repaired one, so it would make a real extension look like no change.
    start = _num(event.get("start"))
    end = _num(event.get("end"))
    if start is None or end is None:
        return None
    src = event.get("_src")
    if src:
        total = _num(duration_fn(src))
        if total is None or total <= 0:
            return None
        end = min(end, total)
    return max(0.0, start), end


def _edit_flags(event: dict[str, Any]) -> tuple[bool, float]:
    edit = event.get("edit") or {}
    return bool(edit.get("slowmo")), round(_num(edit.get("zoom"), 1.0) or 1.0, 2)


def reedit_is_noop(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    duration_fn: Callable[[str], float],
) -> tuple[bool, str]:
    """True when rendering `after` would reproduce `before`, with a short reason.

    Conservative: anything it cannot compare (unknown source duration, different clip count, a changed
    window, slow-motion or zoom) counts as a real change, which keeps the old re-edit behaviour.
    """
    try:
        old = [e for e in before or [] if not e.get("_teaser")]
        new = [e for e in after or [] if not e.get("_teaser")]
        if not old or len(old) != len(new):
            return False, ""
        notes: list[str] = []
        for a, b in zip(old, new):
            if a.get("_src") != b.get("_src") or str(a.get("type")) != str(b.get("type")):
                return False, ""
            wa, wb = _effective_window(a, duration_fn), _effective_window(b, duration_fn)
            if wa is None or wb is None:
                return False, ""
            if abs(wa[0] - wb[0]) > WINDOW_TOLERANCE_SEC or abs(wa[1] - wb[1]) > WINDOW_TOLERANCE_SEC:
                return False, ""
            if _edit_flags(a) != _edit_flags(b):
                return False, ""
            if _num(b.get("end"), 0.0) > wb[1] + WINDOW_TOLERANCE_SEC:
                notes.append(f"source ends at {wb[1]:.1f}s")
        return True, "; ".join(notes) or "same windows and edit settings"
    except Exception:  # fail open: an unexpected shape must never block a re-edit
        return False, ""

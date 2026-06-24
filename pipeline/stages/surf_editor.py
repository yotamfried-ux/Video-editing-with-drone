"""Surf-specific editorial policy layer for the generic FFmpeg editor.

This module intentionally keeps the heavy FFmpeg implementation in
``pipeline.stages.editor``. It patches only deterministic editorial decisions
that are provably too generic from the code alone:

- narrative ordering should not be pure score sorting;
- teaser clips should be short hooks, not full duplicate moments;
- surf clips need event-type-aware duration caps;
- tight zoom near frame edges should be avoided when no tracking exists.

The policy is conservative: it activates only for surfing/wave event types and
falls back to the original editor behavior for other sports.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Callable, Iterable

_SURF_TYPES = {
    "aerial", "barrel", "tube_ride", "wave_catch", "cutback", "bottom_turn",
    "carve", "snap", "paddle", "wipeout", "near_miss",
}

_HIGH_IMPACT = {"aerial", "barrel", "tube_ride", "snap", "cutback", "carve"}
_START_IMPORTANT = {"wave_catch", "bottom_turn", "paddle"}
_LOW_VALUE = {"paddle", "wipeout"}

_TYPE_WEIGHT = {
    "aerial": 6,
    "barrel": 6,
    "tube_ride": 6,
    "snap": 5,
    "cutback": 5,
    "carve": 4,
    "bottom_turn": 3,
    "wave_catch": 3,
    "near_miss": 2,
    "wipeout": 1,
    "paddle": 0,
}

_ORIGINALS: dict[str, Callable] = {}


def _event_type(event: dict) -> str:
    return str(event.get("type", "")).lower()


def _duration(event: dict) -> float:
    try:
        return max(0.0, float(event.get("end", 0)) - float(event.get("start", 0)))
    except (TypeError, ValueError):
        return 0.0


def _score(event: dict) -> int:
    try:
        return int(event.get("score", 0))
    except (TypeError, ValueError):
        return 0


def _is_surf_timeline(events: Iterable[dict]) -> bool:
    items = list(events)
    if not items:
        return False
    surf_count = sum(1 for event in items if _event_type(event) in _SURF_TYPES)
    return surf_count >= max(1, len(items) // 2)


def _impact(event: dict) -> float:
    """Rank a surf event for hook/climax selection.

    Scores still matter, but event type and duration matter too. A score-8 snap
    can be a better Instagram hook than a score-9 long paddle/wave setup.
    """
    typ = _event_type(event)
    dur = _duration(event)
    duration_penalty = max(0.0, dur - 8.0) * 0.7
    low_value_penalty = 8 if typ in _LOW_VALUE else 0
    return _score(event) * 10 + _TYPE_WEIGHT.get(typ, 2) * 3 - duration_penalty - low_value_penalty


def _with_transition(event: dict, index: int, total: int) -> dict:
    """Apply surf-aware transition hints without mutating the source event."""
    ev = deepcopy(event)
    edit = dict(ev.get("edit") or {})
    typ = _event_type(ev)

    if index == 0 or typ in _HIGH_IMPACT:
        edit["transition_out"] = "cut"
    elif typ in {"wave_catch", "bottom_turn"}:
        edit["transition_out"] = "slide"
    else:
        edit.setdefault("transition_out", "slide")

    # Reserve zoom transition only for the build into the final climax.
    if index != total - 2 and edit.get("transition_out") == "zoom":
        edit["transition_out"] = "slide"

    # Avoid forced slow-mo on low-value setup moments.
    if typ in _LOW_VALUE:
        edit["slowmo"] = False

    ev["edit"] = edit
    return ev


def order_surf_events(events: list[dict]) -> list[dict]:
    """Return a deterministic surf-edit order: hook → build → climax.

    This replaces the generic "second-best opens, best closes" formula with a
    surf-specific timeline that chooses a high-impact, short hook, keeps the best
    moment as the closer, and orders the build by rising editorial impact while
    preserving variety between repeated move types.
    """
    if len(events) <= 2 or not _is_surf_timeline(events):
        return list(events)

    pool = [deepcopy(event) for event in events]
    climax = max(pool, key=_impact)
    remaining = [event for event in pool if event is not climax]

    hook_candidates = [
        event for event in remaining
        if _event_type(event) not in _LOW_VALUE and _duration(event) <= 10.0
    ] or remaining
    hook = max(hook_candidates, key=_impact)
    remaining = [event for event in remaining if event is not hook]

    middle = sorted(remaining, key=lambda event: (_impact(event), float(event.get("start", 0))))

    # Keep variety: avoid adjacent identical surf move types when a simple swap can fix it.
    for idx in range(1, len(middle)):
        if _event_type(middle[idx]) != _event_type(middle[idx - 1]):
            continue
        swap_idx = next(
            (j for j in range(idx + 1, len(middle))
             if _event_type(middle[j]) != _event_type(middle[idx])),
            None,
        )
        if swap_idx is not None:
            middle[idx], middle[swap_idx] = middle[swap_idx], middle[idx]

    ordered = [hook] + middle + [climax]
    return [_with_transition(event, idx, len(ordered)) for idx, event in enumerate(ordered)]


def refine_surf_event_window(event: dict) -> dict:
    """Conservatively trim surf event windows before the generic FFmpeg cut.

    Without visual tracking we should not invent a new cut. This only caps overly
    long generic windows and keeps either the setup or payoff depending on event
    type.
    """
    typ = _event_type(event)
    if typ not in _SURF_TYPES and not event.get("_teaser"):
        return event

    ev = deepcopy(event)
    start = float(ev.get("start", 0.0))
    end = float(ev.get("end", start))
    dur = max(0.0, end - start)

    if ev.get("_teaser"):
        cap = 1.6
    elif ev.get("_is_climax"):
        cap = 12.0 if typ in {"barrel", "tube_ride"} else 10.5
    elif _score(ev) <= 6:
        cap = 5.5
    else:
        cap = 7.5 if typ not in {"barrel", "tube_ride"} else 9.0

    if dur > cap:
        if typ in _START_IMPORTANT:
            end = start + cap
        else:
            start = end - cap
        ev["start"] = round(start, 2)
        ev["end"] = round(end, 2)

    edit = dict(ev.get("edit") or {})
    crop_x = float(ev.get("crop_x", 0.5))
    # With static crop_x/crop_y and no tracking, tight zoom at the frame edges is risky.
    if crop_x < 0.18 or crop_x > 0.82:
        edit["zoom"] = min(float(edit.get("zoom", 1.0)), 1.15)
        edit["focus"] = "full"
    if typ in _LOW_VALUE:
        edit["slowmo"] = False
    ev["edit"] = edit
    return ev


def install_surf_editor_patches() -> None:
    """Install conservative surf-edit improvements into ``pipeline.stages.editor``."""
    from pipeline.stages import editor

    if _ORIGINALS.get("installed"):
        return

    _ORIGINALS["_narrative_order"] = editor._narrative_order
    _ORIGINALS["cut_clip"] = editor.cut_clip

    original_narrative = editor._narrative_order
    original_cut_clip = editor.cut_clip

    def surf_narrative_order(events: list[dict]) -> list[dict]:
        if not _is_surf_timeline(events):
            return original_narrative(events)
        ordered = order_surf_events(events)
        # Reuse the editor's existing rule: one slow-mo clip max, reserved for climax.
        return editor._enforce_single_slowmo(ordered)

    def surf_cut_clip(
        video_path: str,
        event: dict,
        index: int,
        slowmo: bool = False,
        sport: str = "",
        source_info: dict | None = None,
        session_peak: int = 10,
        target_fps: int | None = None,
    ) -> str | None:
        is_surf = sport.lower() == "surfing" or _event_type(event) in _SURF_TYPES or event.get("_teaser")
        refined = refine_surf_event_window(event) if is_surf else event
        return original_cut_clip(
            video_path, refined, index, slowmo, sport, source_info, session_peak, target_fps
        )

    editor._narrative_order = surf_narrative_order
    editor.cut_clip = surf_cut_clip
    _ORIGINALS["installed"] = True

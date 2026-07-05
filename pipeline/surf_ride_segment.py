"""Surf ride continuity normalization."""
from __future__ import annotations

from typing import Any

SURF_TERMS = {"surf", "surfing", "surfer", "wave", "longboard", "shortboard", "cutback", "carve", "snap", "ride", "paddle"}
MERGE_GAP_SEC = 7.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _src(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def _is_surf(event: dict[str, Any], sport: str = "") -> bool:
    text = " ".join([sport, str(event.get("sport", "")), str(event.get("type", "")), str(event.get("description", ""))]).lower()
    return any(term in text for term in SURF_TERMS)


def _track(event: dict[str, Any]) -> str:
    return str(event.get("track_id") or event.get("person_id") or event.get("athlete_id") or "")


def _start(event: dict[str, Any]) -> float:
    return _num(event.get("ride_start", event.get("takeoff_time", event.get("start"))))


def _end(event: dict[str, Any]) -> float:
    return _num(event.get("ride_end", event.get("outcome_end", event.get("landing_time", event.get("end")))))


def _peak(event: dict[str, Any]) -> float:
    return _num(event.get("peak_time", event.get("action_time", (_start(event) + _end(event)) / 2)))


def _can_merge(a: dict[str, Any], b: dict[str, Any], sport: str) -> bool:
    if not (_is_surf(a, sport) and _is_surf(b, sport)):
        return False
    if _src(a) and _src(b) and _src(a) != _src(b):
        return False
    ta, tb = _track(a), _track(b)
    if ta and tb and ta != tb:
        return False
    return _start(b) <= _end(a) + MERGE_GAP_SEC


def _merge_group(group: list[dict[str, Any]], sport: str) -> dict[str, Any]:
    first = group[0]
    start = min(_start(e) for e in group)
    end = max(_end(e) for e in group)
    peak = max(group, key=lambda e: _num(e.get("score"), 0))
    tracks = {t for t in (_track(e) for e in group) if t}
    explicit_end = any(e.get("ride_end") is not None or e.get("outcome_end") is not None or e.get("landing_time") is not None for e in group)
    identity_uncertain = len(tracks) != 1
    merged = {**first, "start": start, "end": end, "ride_start": start, "takeoff_time": start, "peak_time": _peak(peak), "ride_end": end, "outcome_end": end, "source": _src(first), "_src": _src(first), "type": "surf_ride", "score": max(_num(e.get("score"), 0) for e in group), "ride_segment": True, "ride_fragment_count": len(group), "ride_boundary_uncertain": not explicit_end, "identity_uncertain": identity_uncertain}
    if len(tracks) == 1:
        merged["track_id"] = next(iter(tracks))
    if len(group) > 1:
        merged["merged_ride_fragments"] = [{"event_id": e.get("event_id") or e.get("id"), "start": e.get("start"), "end": e.get("end"), "score": e.get("score"), "track_id": e.get("track_id")} for e in group]
    defects = []
    if not explicit_end:
        defects.append({"type": "RIDE_BOUNDARY_UNCERTAIN", "defect_type": "RIDE_BOUNDARY_UNCERTAIN", "severity": "critical", "blocking": True, "note": "ride end was inferred from fragments"})
    if identity_uncertain:
        defects.append({"type": "IDENTITY_UNCERTAIN", "defect_type": "IDENTITY_UNCERTAIN", "severity": "critical", "blocking": True, "note": "stable athlete track evidence is missing across the ride"})
    if defects:
        merged["ride_qa_defects"] = defects
        merged["dedup_dropped_duplicates"] = [*(merged.get("dedup_dropped_duplicates", []) or []), *defects]
    return merged


def normalize_surf_rides(events: list[dict[str, Any]], sport: str = "") -> list[dict[str, Any]]:
    if not events:
        return []
    ordered = sorted(events, key=_start)
    out: list[dict[str, Any]] = []
    group: list[dict[str, Any]] = []
    for event in ordered:
        if not _is_surf(event, sport):
            if group:
                out.append(_merge_group(group, sport)); group = []
            out.append(event)
            continue
        if not group or _can_merge(group[-1], event, sport):
            group.append(event)
        else:
            out.append(_merge_group(group, sport)); group = [event]
    if group:
        out.append(_merge_group(group, sport))
    return out

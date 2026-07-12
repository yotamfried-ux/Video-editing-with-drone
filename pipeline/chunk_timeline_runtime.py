"""Chunk-safe identity and timestamp normalization for long source videos.

Gemini reuses labels such as ``person_A`` independently in every uploaded chunk.
Those labels are local to a chunk and must never be treated as run-global identity.
Gemini can also return either chunk-local timestamps or source-global timestamps;
this module resolves that ambiguity against deterministic chunk bounds before any
selection, rendering, or telemetry stage sees the events.
"""
from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_MIN_USABLE_EVENT_SEC = 4.0
_BOUNDARY_TOLERANCE_SEC = 1.0
_ACTIVE_SOURCE: ContextVar[tuple[str, float] | None] = ContextVar("sportreel_chunk_source", default=None)
_INSTALL_FLAG = "_sportreel_chunk_timeline_runtime_installed"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_duration(path: str) -> float:
    from integrations.ffmpeg import get_duration

    return float(get_duration(path))


def build_chunk_specs(source_duration_sec: float, segment_sec: float, chunk_count: int) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for index in range(max(0, chunk_count)):
        start = index * segment_sec
        remaining = max(0.0, source_duration_sec - start)
        duration = min(segment_sec, remaining) if chunk_count > 1 else source_duration_sec
        specs.append({
            "chunk_index": index,
            "source_start": round(start, 3),
            "duration": round(duration, 3),
            "source_end": round(min(source_duration_sec, start + duration), 3),
        })
    return specs


def namespace_person_id(chunk_index: int, person_id: Any) -> str:
    local = str(person_id or "person_?").strip() or "person_?"
    return f"chunk_{chunk_index:02d}:{local}"


def runtime_person_id(chunk_count: int, chunk_index: int, person_id: Any) -> str:
    """Namespace only when local model labels can collide across real chunks."""
    local = str(person_id or "person_?").strip() or "person_?"
    return namespace_person_id(chunk_index, local) if chunk_count > 1 else local


def _usable_overlap(start: float, end: float, duration: float) -> float:
    return max(0.0, min(duration, end) - max(0.0, start))


def _choose_timestamp_basis(
    raw_start: float,
    raw_end: float,
    *,
    offset: float,
    duration: float,
    source_end: float,
) -> tuple[str, float, float] | None:
    candidates: list[tuple[float, int, str, float, float]] = []
    if -_BOUNDARY_TOLERANCE_SEC <= raw_start < duration + _BOUNDARY_TOLERANCE_SEC:
        candidates.append((_usable_overlap(raw_start, raw_end, duration), 1, "chunk_local", raw_start, raw_end))
    if offset > 0 and offset - _BOUNDARY_TOLERANCE_SEC <= raw_start < source_end + _BOUNDARY_TOLERANCE_SEC:
        local_start, local_end = raw_start - offset, raw_end - offset
        candidates.append((_usable_overlap(local_start, local_end, duration), 0, "source_global", local_start, local_end))
    if not candidates:
        return None
    # Prefer the interpretation with the most usable time inside the real chunk.
    # A tie prefers chunk-local values because Gemini is prompted on the chunk file.
    _overlap, _local_preference, basis, start, end = max(candidates, key=lambda item: (item[0], item[1]))
    return basis, start, end


def normalize_chunk_window(
    start_value: Any,
    end_value: Any,
    spec: dict[str, Any],
    *,
    min_duration_sec: float = _MIN_USABLE_EVENT_SEC,
) -> dict[str, Any]:
    """Resolve local/global timestamp basis and clamp to one chunk's real bounds."""
    raw_start = _num(start_value)
    raw_end = _num(end_value)
    offset = float(spec.get("source_start") or 0.0)
    duration = float(spec.get("duration") or 0.0)
    source_end = float(spec.get("source_end") or offset + duration)
    if raw_start is None or raw_end is None or raw_end <= raw_start or duration <= 0:
        return {"valid": False, "reason": "invalid_numeric_window", "raw_start": raw_start, "raw_end": raw_end}

    chosen = _choose_timestamp_basis(raw_start, raw_end, offset=offset, duration=duration, source_end=source_end)
    if chosen is None:
        return {
            "valid": False,
            "reason": "timestamp_outside_chunk_bounds",
            "raw_start": raw_start,
            "raw_end": raw_end,
            "chunk_start": offset,
            "chunk_duration": duration,
        }

    basis, local_start, local_end = chosen
    clamped_start = max(0.0, local_start)
    clamped_end = min(duration, local_end)
    was_clamped = abs(clamped_start - local_start) > 0.001 or abs(clamped_end - local_end) > 0.001
    if clamped_start >= duration or clamped_end - clamped_start < min_duration_sec:
        return {
            "valid": False,
            "reason": "insufficient_time_inside_chunk",
            "timestamp_basis": basis,
            "raw_start": raw_start,
            "raw_end": raw_end,
            "chunk_local_start": round(clamped_start, 3),
            "chunk_local_end": round(clamped_end, 3),
            "chunk_start": offset,
            "chunk_duration": duration,
        }

    global_start = offset + clamped_start
    global_end = min(source_end, offset + clamped_end)
    return {
        "valid": True,
        "timestamp_basis": basis,
        "timestamp_clamped": was_clamped,
        "raw_start": round(raw_start, 3),
        "raw_end": round(raw_end, 3),
        "chunk_local_start": round(clamped_start, 3),
        "chunk_local_end": round(clamped_end, 3),
        "source_start": round(global_start, 2),
        "source_end": round(global_end, 2),
        "duration": round(global_end - global_start, 2),
    }


def _normalize_event(
    event: dict[str, Any],
    *,
    spec: dict[str, Any],
    source_video: str,
    person_id: str,
    source_person_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    window = normalize_chunk_window(event.get("start"), event.get("end"), spec)
    if not window.get("valid"):
        return None, window
    return ({
        **event,
        "start": window["source_start"],
        "end": window["source_end"],
        "duration": window["duration"],
        "source_video": source_video,
        "person_id": person_id,
        "chunk_person_id": person_id,
        "source_person_id": source_person_id,
        "chunk_index": spec["chunk_index"],
        "chunk_source_start": spec["source_start"],
        "chunk_source_end": spec["source_end"],
        "chunk_local_start": window["chunk_local_start"],
        "chunk_local_end": window["chunk_local_end"],
        "timestamp_basis": window["timestamp_basis"],
        "timestamp_clamped": window["timestamp_clamped"],
        "raw_chunk_start": window["raw_start"],
        "raw_chunk_end": window["raw_end"],
    }, window)


def merge_chunk_sessions(
    chunk_results: list[dict[str, Any]],
    *,
    segment_sec: float,
    source_duration_sec: float,
    source_video: str,
) -> dict[str, Any]:
    """Merge chunks without conflating local person labels or double-shifting time."""
    chunk_count = len(chunk_results)
    specs = build_chunk_specs(source_duration_sec, segment_sec, chunk_count)
    activities = [
        result.get("activity", "unknown")
        for result in chunk_results
        if result.get("activity") not in {"unknown", "other", ""}
    ]
    activity = Counter(activities).most_common(1)[0][0] if activities else "sport"
    persons: list[dict[str, Any]] = []
    invalid_events: list[dict[str, Any]] = []
    basis_counts: Counter[str] = Counter()
    clamped_count = 0

    for chunk_index, result in enumerate(chunk_results):
        spec = specs[chunk_index]
        for person in result.get("persons", []) or []:
            if not isinstance(person, dict):
                continue
            source_person_id = str(person.get("id") or "person_?")
            person_id = runtime_person_id(chunk_count, chunk_index, source_person_id)
            events: list[dict[str, Any]] = []
            for event_index, event in enumerate(person.get("events", []) or []):
                if not isinstance(event, dict):
                    continue
                normalized, evidence = _normalize_event(
                    event,
                    spec=spec,
                    source_video=source_video,
                    person_id=person_id,
                    source_person_id=source_person_id,
                )
                if normalized is None:
                    invalid_events.append({
                        "chunk_index": chunk_index,
                        "person_id": person_id,
                        "event_index": event_index,
                        "event_type": event.get("type"),
                        "description": event.get("description", ""),
                        **evidence,
                    })
                    continue
                basis_counts[str(normalized.get("timestamp_basis"))] += 1
                if normalized.get("timestamp_clamped"):
                    clamped_count += 1
                events.append(normalized)
            if not events:
                continue
            persons.append({
                **person,
                "id": person_id,
                "source_person_id": source_person_id,
                "chunk_person_id": person_id,
                "chunk_index": chunk_index,
                "chunk_source_start": spec["source_start"],
                "chunk_source_end": spec["source_end"],
                "source_video": source_video,
                "events": events,
            })

    styles = [result.get("style") for result in chunk_results if result.get("style")]
    return {
        "activity": activity,
        "persons": persons,
        "style": styles[0] if styles else {},
        "session_peak": max((result.get("session_peak", 0) for result in chunk_results), default=0),
        "source_profile": next((result.get("source_profile") for result in chunk_results if result.get("source_profile")), None),
        "diagnostics": {
            "chunk_timeline_contract": {
                "source_video": source_video,
                "source_duration_sec": round(source_duration_sec, 3),
                "chunk_count": chunk_count,
                "namespaced_person_count": sum(1 for person in persons if str(person.get("id", "")).startswith("chunk_")),
                "invalid_timestamp_event_count": len(invalid_events),
                "clamped_timestamp_event_count": clamped_count,
                "timestamp_basis_counts": dict(basis_counts),
                "invalid_timestamp_events": invalid_events,
            }
        },
    }


def merge_selector_payloads(
    payloads: list[dict[str, Any]],
    *,
    source_video: str,
    segment_sec: float,
    source_duration_sec: float,
) -> dict[str, Any]:
    chunk_count = len(payloads)
    specs = build_chunk_specs(source_duration_sec, segment_sec, chunk_count)
    candidates: list[dict[str, Any]] = []
    invalid_count = 0
    clamped_count = 0
    basis_counts: Counter[str] = Counter()

    for chunk_index, payload in enumerate(payloads):
        spec = specs[chunk_index]
        for raw in payload.get("candidates", []) or []:
            if not isinstance(raw, dict):
                continue
            candidate = dict(raw)
            source_person_id = str(candidate.get("person_id") or "person_?")
            person_id = runtime_person_id(chunk_count, chunk_index, source_person_id)
            window = candidate.get("source_window") if isinstance(candidate.get("source_window"), dict) else {}
            normalized = normalize_chunk_window(window.get("start"), window.get("end"), spec)
            candidate.update({
                "source_video": source_video,
                "person_id": person_id,
                "chunk_person_id": person_id,
                "source_person_id": source_person_id,
                "chunk_index": chunk_index,
                "chunk_source_start": spec["source_start"],
                "chunk_source_end": spec["source_end"],
                "selector_original_selected": bool(candidate.get("selected")),
            })
            if not normalized.get("valid"):
                invalid_count += 1
                candidate.update({
                    "selected": False,
                    "discarded": True,
                    "selection_reason": None,
                    "discard_cause": str(normalized.get("reason") or "timestamp_outside_chunk_bounds"),
                    "source_window": {
                        "start": normalized.get("raw_start"),
                        "end": normalized.get("raw_end"),
                        "duration": None,
                    },
                    "timestamp_validation": normalized,
                })
            else:
                basis_counts[str(normalized.get("timestamp_basis"))] += 1
                if normalized.get("timestamp_clamped"):
                    clamped_count += 1
                candidate.update({
                    "source_window": {
                        "start": normalized["source_start"],
                        "end": normalized["source_end"],
                        "duration": normalized["duration"],
                    },
                    "chunk_local_window": {
                        "start": normalized["chunk_local_start"],
                        "end": normalized["chunk_local_end"],
                    },
                    "timestamp_basis": normalized["timestamp_basis"],
                    "timestamp_clamped": normalized["timestamp_clamped"],
                })
            candidates.append(candidate)

    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded_count = sum(1 for item in candidates if item.get("discarded"))
    return {
        "schema_version": "sportreel.selector_candidate_events.v1",
        "source_video": source_video,
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": discarded_count,
        "discard_causes_available": discarded_count > 0 and all(item.get("discard_cause") for item in candidates if item.get("discarded")),
        "chunk_timeline_summary": {
            "source_duration_sec": round(source_duration_sec, 3),
            "chunk_count": chunk_count,
            "person_ids_namespaced": chunk_count > 1,
            "invalid_timestamp_candidate_count": invalid_count,
            "clamped_timestamp_candidate_count": clamped_count,
            "timestamp_basis_counts": dict(basis_counts),
        },
        "candidates": candidates,
    }


def install() -> None:
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, _INSTALL_FLAG, False):
        return
    original_analyze = analyzer.analyze_session
    original_merge = analyzer._merge_session_results

    def merge_with_contract(chunk_results, seg_secs):
        active = _ACTIVE_SOURCE.get()
        if active is None:
            return original_merge(chunk_results, seg_secs)
        source_path, duration = active
        return merge_chunk_sessions(
            chunk_results,
            segment_sec=float(seg_secs),
            source_duration_sec=float(duration),
            source_video=Path(source_path).name,
        )

    def analyze_with_chunk_contract(video_path: str, *args, **kwargs):
        try:
            duration = source_duration(video_path)
        except Exception:
            return original_analyze(video_path, *args, **kwargs)
        token = _ACTIVE_SOURCE.set((str(video_path), duration))
        try:
            return original_analyze(video_path, *args, **kwargs)
        finally:
            _ACTIVE_SOURCE.reset(token)

    analyzer._merge_session_results = merge_with_contract
    analyzer.analyze_session = analyze_with_chunk_contract
    setattr(analyzer, _INSTALL_FLAG, True)

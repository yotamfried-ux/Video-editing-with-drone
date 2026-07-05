"""Run-level context QA gate.

This gate evaluates all draft candidates in one run before upload. It does not
replace reel-level Gemini QA; it adds deterministic run-level checks that need
edit/source context, especially duplicate rendered drafts with different names.
"""
from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _src(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _fingerprint(event: dict[str, Any]) -> str:
    for key in ("event_fingerprint", "fingerprint", "visual_hash", "clip_hash"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _bucket_time(value: Any) -> int:
    return int(round(_num(value) * 2))  # half-second buckets


def event_window_key(event: dict[str, Any], index: int) -> tuple[Any, ...]:
    fp = _fingerprint(event)
    if fp:
        return ("fp", fp)
    return (
        "window",
        _src(event),
        _event_id(event, index),
        _bucket_time(event.get("start")),
        _bucket_time(event.get("end")),
        str(event.get("track_id") or ""),
    )


def draft_fingerprint(events: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    keys = [event_window_key(event, idx) for idx, event in enumerate(events) if not event.get("_teaser")]
    return tuple(sorted(keys))


def draft_quality(events: list[dict[str, Any]]) -> float:
    total = 0.0
    for event in events:
        if event.get("_teaser"):
            continue
        visible = max(0.0, min(1.0, _num(event.get("visible_ratio"), 1.0)))
        confidence = max(0.0, min(1.0, _num(event.get("perception_confidence"), _num(event.get("confidence"), 1.0))))
        total += _num(event.get("score")) + visible + confidence
    return total


def build_qa_package(reel_path: str, draft_name: str, events: list[dict[str, Any]], source_quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "reel_path": reel_path,
        "draft_name": draft_name,
        "fingerprint": draft_fingerprint(events),
        "quality": draft_quality(events),
        "events": events,
        "source_quality": source_quality,
        "source_windows": [
            {
                "event_id": _event_id(event, idx),
                "source": _src(event),
                "start": event.get("start"),
                "end": event.get("end"),
                "final_cut_start": event.get("final_cut_start"),
                "final_cut_end": event.get("final_cut_end"),
                "track_id": event.get("track_id"),
                "fingerprint": _fingerprint(event),
            }
            for idx, event in enumerate(events)
            if not event.get("_teaser")
        ],
    }


def _duplicate_detail(dropped: dict[str, Any], kept: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason": "duplicate_rendered_draft",
        "defect_type": "DUPLICATE_DRAFT",
        "blocking": True,
        "dropped_draft": dropped["draft_name"],
        "kept_draft": kept["draft_name"],
        "dropped_source_windows": dropped["source_windows"],
        "kept_source_windows": kept["source_windows"],
    }


def _attach_duplicate_detail(events: list[dict[str, Any]], detail: dict[str, Any]) -> list[dict[str, Any]]:
    if not events:
        return events
    first = {**events[0], "dedup_dropped_duplicates": [*(events[0].get("dedup_dropped_duplicates", []) or []), detail]}
    return [first, *events[1:]]


def filter_duplicate_draft_candidates(pending: list[tuple[str, str]], pending_meta: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]]) -> tuple[list[tuple[str, str]], list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]], list[dict[str, Any]]]:
    packages = [build_qa_package(reel, name, events, src_q) for reel, name, events, src_q in pending_meta]
    keep_by_fp: dict[tuple[tuple[Any, ...], ...], int] = {}
    dropped: list[dict[str, Any]] = []

    for idx, package in enumerate(packages):
        fp = package["fingerprint"]
        if not fp:
            keep_by_fp[(('empty', idx),)] = idx
            continue
        if fp not in keep_by_fp:
            keep_by_fp[fp] = idx
            continue
        kept_idx = keep_by_fp[fp]
        kept = packages[kept_idx]
        if package["quality"] > kept["quality"]:
            dropped.append(_duplicate_detail(kept, package))
            keep_by_fp[fp] = idx
        else:
            dropped.append(_duplicate_detail(package, kept))

    kept_indices = set(keep_by_fp.values())
    filtered_pending: list[tuple[str, str]] = []
    filtered_meta: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]] = []
    by_kept_name: dict[str, list[dict[str, Any]]] = {}
    for detail in dropped:
        by_kept_name.setdefault(detail["kept_draft"], []).append(detail)

    for idx, meta in enumerate(pending_meta):
        if idx not in kept_indices:
            continue
        reel, name, events, src_q = meta
        for detail in by_kept_name.get(name, []):
            events = _attach_duplicate_detail(events, detail)
        filtered_pending.append(pending[idx])
        filtered_meta.append((reel, name, events, src_q))
    return filtered_pending, filtered_meta, dropped

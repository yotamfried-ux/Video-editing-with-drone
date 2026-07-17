#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

WindowKey = tuple[str, float | None, float | None, str, str]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _candidate_id(draft_id: str, idx: int, window: dict[str, Any]) -> str:
    seed = json.dumps({"draft_id": draft_id, "idx": idx, "window": window}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _float_or_none(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _window_key(candidate: dict[str, Any], field: str = "source_window") -> WindowKey:
    window = candidate.get(field) if isinstance(candidate.get(field), dict) else {}
    return (
        str(candidate.get("source_video") or ""),
        _float_or_none(window.get("start")),
        _float_or_none(window.get("end")),
        str(candidate.get("event_type") or ""),
        str(candidate.get("person_id") or candidate.get("chunk_person_id") or ""),
    )


def _candidate_window_keys(candidate: dict[str, Any]) -> list[WindowKey]:
    keys = [_window_key(candidate)]
    original = _window_key(candidate, "original_source_window")
    if original[1] is not None and original[2] is not None and original not in keys:
        keys.append(original)
    return keys


def _keys_match(left: WindowKey, right: WindowKey) -> bool:
    source_ok = left[0] == right[0] or not left[0] or not right[0]
    time_type_ok = left[1:4] == right[1:4]
    person_ok = left[4] == right[4] or not left[4] or not right[4]
    return source_ok and time_type_ok and person_ok


def _find_matching_key(candidate: dict[str, Any], by_key: dict[WindowKey, dict[str, Any]]) -> WindowKey | None:
    for candidate_key in _candidate_window_keys(candidate):
        if candidate_key in by_key:
            return candidate_key
        for stored_key in by_key:
            if _keys_match(candidate_key, stored_key):
                return stored_key
    return None


def _matches_any_trace(candidate: dict[str, Any], trace_candidates: list[dict[str, Any]]) -> bool:
    candidate_keys = _candidate_window_keys(candidate)
    return any(
        _keys_match(candidate_key, trace_key)
        for trace_candidate in trace_candidates
        for candidate_key in candidate_keys
        for trace_key in _candidate_window_keys(trace_candidate)
    )


def _lineage_value(window: dict[str, Any], draft: dict[str, Any], key: str) -> Any:
    value = window.get(key)
    if value is not None and str(value).strip():
        return value
    value = draft.get(key)
    if value is not None and str(value).strip():
        return value
    values = draft.get(f"{key}s")
    if isinstance(values, list) and len(values) == 1:
        return values[0]
    return None


def _candidate_from_window(draft: dict[str, Any], idx: int, window: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(draft.get("draft_id") or draft.get("draft_name") or "unknown_draft")
    original_start = window.get("original_start")
    original_end = window.get("original_end")
    original_duration = None
    if isinstance(original_start, (int, float)) and isinstance(original_end, (int, float)):
        original_duration = float(original_end) - float(original_start)
    return {
        "candidate_id": _candidate_id(draft_id, idx, window),
        "draft_id": draft_id,
        "draft_name": draft.get("draft_name") or draft_id,
        "person_id": _lineage_value(window, draft, "person_id"),
        "source_person_id": _lineage_value(window, draft, "source_person_id"),
        "chunk_person_id": _lineage_value(window, draft, "chunk_person_id"),
        "athlete_id": _lineage_value(window, draft, "athlete_id"),
        "athlete_canonical_key": window.get("athlete_canonical_key"),
        "athlete_canonical_evidence_status": window.get("athlete_canonical_evidence_status"),
        "identity_lineage_status": draft.get("identity_lineage_status"),
        "selected": True,
        "discarded": False,
        "discard_cause": None,
        "selection_reason": "selected_for_uploaded_draft",
        "event_type": window.get("event_type", ""),
        "score": window.get("score"),
        "source_video": window.get("source_video"),
        "source_window": {
            "start": window.get("start"),
            "end": window.get("end"),
            "duration": window.get("duration"),
        },
        "original_source_window": {
            "start": original_start,
            "end": original_end,
            "duration": original_duration,
        },
        "chunk_index": window.get("chunk_index"),
        "chunk_local_start": window.get("chunk_local_start"),
        "chunk_local_end": window.get("chunk_local_end"),
        "timestamp_basis": window.get("timestamp_basis"),
        "description": window.get("description", ""),
    }


def _selected_from_trace(trace: dict[str, Any]) -> list[dict[str, Any]]:
    drafts = [draft for draft in trace.get("drafts", []) if isinstance(draft, dict)]
    candidates: list[dict[str, Any]] = []
    for draft in drafts:
        windows = [window for window in draft.get("source_windows", []) if isinstance(window, dict)]
        if not windows and isinstance(draft.get("source_window"), dict):
            windows = [draft["source_window"]]
        for idx, window in enumerate(windows):
            candidates.append(_candidate_from_window(draft, idx, window))
    return candidates


def _normalized_upstream_candidates(upstream: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(upstream.get("candidates", []) if isinstance(upstream.get("candidates"), list) else []):
        if not isinstance(raw, dict):
            continue
        window = raw.get("source_window") if isinstance(raw.get("source_window"), dict) else {}
        selected = bool(raw.get("selected"))
        discarded = bool(raw.get("discarded"))
        if selected and discarded:
            discarded = False
        out.append({
            "candidate_id": raw.get("candidate_id") or _candidate_id(str(raw.get("draft_id") or raw.get("person_id") or "upstream"), idx, window),
            "draft_id": raw.get("draft_id"),
            "draft_name": raw.get("draft_name"),
            "person_id": raw.get("person_id"),
            "source_person_id": raw.get("source_person_id"),
            "chunk_person_id": raw.get("chunk_person_id"),
            "athlete_id": raw.get("athlete_id"),
            "person_description": raw.get("person_description"),
            "selected": selected,
            "discarded": discarded,
            "discard_cause": raw.get("discard_cause") if discarded else None,
            "selection_reason": raw.get("selection_reason") if selected else None,
            "event_type": raw.get("event_type", ""),
            "score": raw.get("score"),
            "source_video": raw.get("source_video"),
            "source_window": {
                "start": window.get("start"),
                "end": window.get("end"),
                "duration": window.get("duration"),
            },
            "chunk_index": raw.get("chunk_index"),
            "chunk_local_start": (raw.get("chunk_local_window") or {}).get("start") if isinstance(raw.get("chunk_local_window"), dict) else raw.get("chunk_local_start"),
            "chunk_local_end": (raw.get("chunk_local_window") or {}).get("end") if isinstance(raw.get("chunk_local_window"), dict) else raw.get("chunk_local_end"),
            "timestamp_basis": raw.get("timestamp_basis"),
            "description": raw.get("description", ""),
        })
    return out


def _unmatched_upstream_selected_to_discarded(candidate: dict[str, Any]) -> dict[str, Any]:
    converted = dict(candidate)
    converted.update({
        "selected": False,
        "discarded": True,
        "discard_cause": "selected_by_selector_not_emitted_as_draft",
        "selection_reason": None,
        "unmatched_selector_selection": True,
    })
    return converted


def _merge_candidates(trace_candidates: list[dict[str, Any]], upstream_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not upstream_candidates:
        return trace_candidates

    by_key: dict[WindowKey, dict[str, Any]] = {}
    for item in upstream_candidates:
        key = _window_key(item)
        candidate = dict(item)
        if candidate.get("selected") and not _matches_any_trace(candidate, trace_candidates):
            candidate = _unmatched_upstream_selected_to_discarded(candidate)
        by_key[key] = candidate

    lineage_keys = (
        "person_id",
        "source_person_id",
        "chunk_person_id",
        "athlete_id",
        "athlete_canonical_key",
        "athlete_canonical_evidence_status",
        "identity_lineage_status",
        "chunk_index",
        "chunk_local_start",
        "chunk_local_end",
        "timestamp_basis",
    )
    for trace_candidate in trace_candidates:
        trace_key = _window_key(trace_candidate)
        existing_key = _find_matching_key(trace_candidate, by_key)
        if existing_key is not None:
            merged = {**by_key.pop(existing_key)}
            merged.update({
                "draft_id": trace_candidate.get("draft_id"),
                "draft_name": trace_candidate.get("draft_name"),
                "selected": True,
                "discarded": False,
                "discard_cause": None,
                "selection_reason": trace_candidate.get("selection_reason") or "selected_for_uploaded_draft",
                "unmatched_selector_selection": False,
                "final_source_window": trace_candidate.get("source_window"),
                "matched_via_original_source_window": existing_key != trace_key,
            })
            for key in lineage_keys:
                if trace_candidate.get(key) is not None:
                    merged[key] = trace_candidate.get(key)
            if trace_candidate.get("source_video"):
                merged["source_video"] = trace_candidate.get("source_video")
            # Keep selector source_window as the action-candidate window and store
            # the actual edited cut separately for utilization/QA diagnostics.
            by_key[existing_key] = merged
        else:
            by_key[trace_key] = trace_candidate
    return list(by_key.values())


def build_ledger(trace_path: Path, upstream_path: Path | None = None) -> dict[str, Any]:
    trace = _read_json(trace_path)
    upstream = _read_json(upstream_path) if upstream_path else {}
    trace_candidates = _selected_from_trace(trace)
    upstream_candidates = _normalized_upstream_candidates(upstream)
    candidates = _merge_candidates(trace_candidates, upstream_candidates)
    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded_count = sum(1 for item in candidates if item.get("discarded"))
    unmatched_selector_selected_count = sum(1 for item in candidates if item.get("unmatched_selector_selection"))
    selected_lineage_complete_count = sum(
        1
        for item in candidates
        if item.get("selected") and item.get("person_id") and item.get("athlete_id") and item.get("source_video")
    )
    discard_causes_available = discarded_count > 0 and all(item.get("discard_cause") for item in candidates if item.get("discarded"))
    return {
        "schema_version": "sportreel.candidate_decision_ledger.v1",
        "source": {
            "draft_decision_trace_path": str(trace_path),
            "source_trace_schema_version": trace.get("schema_version"),
            "upstream_candidate_path": str(upstream_path) if upstream_path else None,
            "upstream_candidate_schema_version": upstream.get("schema_version"),
        },
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": discarded_count,
        "selected_lineage_complete_count": selected_lineage_complete_count,
        "selected_lineage_incomplete_count": max(0, selected_count - selected_lineage_complete_count),
        "unmatched_selector_selected_count": unmatched_selector_selected_count,
        "discard_causes_available": discard_causes_available,
        "recall_status": "selected_and_discarded" if selected_count > 0 and discard_causes_available else "selected_only",
        "known_gap": None if selected_count > 0 and discard_causes_available else "discarded candidates are not yet emitted by the upstream selector",
        "detected_athlete_registry": [
            dict(row) for row in upstream.get("detected_athlete_registry", []) or []
            if isinstance(row, dict)
        ],
        "candidates": candidates,
    }


def main() -> int:
    if len(sys.argv) not in {3, 4}:
        print("usage: build_candidate_decision_ledger.py DRAFT_DECISION_TRACE_JSON OUTPUT_JSON [UPSTREAM_CANDIDATES_JSON]", file=sys.stderr)
        return 2
    upstream_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    ledger = build_ledger(Path(sys.argv[1]), upstream_path)
    _write_json(Path(sys.argv[2]), ledger)
    print(
        "candidate ledger "
        f"candidates={ledger['candidate_count']} "
        f"selected={ledger['selected_count']} "
        f"discarded={ledger['discarded_count']} "
        f"lineage_complete={ledger['selected_lineage_complete_count']} "
        f"recall_status={ledger['recall_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

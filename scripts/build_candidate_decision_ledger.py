#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


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


def _window_key(candidate: dict[str, Any]) -> tuple[str, float | None, float | None, str]:
    window = candidate.get("source_window") if isinstance(candidate.get("source_window"), dict) else {}
    start = window.get("start")
    end = window.get("end")
    try:
        start_f = round(float(start), 2)
    except (TypeError, ValueError):
        start_f = None
    try:
        end_f = round(float(end), 2)
    except (TypeError, ValueError):
        end_f = None
    return (str(candidate.get("source_video") or ""), start_f, end_f, str(candidate.get("event_type") or ""))


def _candidate_from_window(draft: dict[str, Any], idx: int, window: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(draft.get("draft_id") or draft.get("draft_name") or "unknown_draft")
    return {
        "candidate_id": _candidate_id(draft_id, idx, window),
        "draft_id": draft_id,
        "draft_name": draft.get("draft_name") or draft_id,
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
        candidate = {
            "candidate_id": raw.get("candidate_id") or _candidate_id(str(raw.get("draft_id") or raw.get("person_id") or "upstream"), idx, window),
            "draft_id": raw.get("draft_id"),
            "draft_name": raw.get("draft_name"),
            "person_id": raw.get("person_id"),
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
            "description": raw.get("description", ""),
        }
        out.append(candidate)
    return out


def _unmatched_upstream_selected_to_discarded(candidate: dict[str, Any]) -> dict[str, Any]:
    converted = dict(candidate)
    converted["selected"] = False
    converted["discarded"] = True
    converted["discard_cause"] = "selected_by_selector_not_emitted_as_draft"
    converted["selection_reason"] = None
    converted["unmatched_selector_selection"] = True
    return converted


def _merge_candidates(trace_candidates: list[dict[str, Any]], upstream_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not upstream_candidates:
        return trace_candidates
    trace_keys = {_window_key(item) for item in trace_candidates}
    by_key: dict[tuple[str, float | None, float | None, str], dict[str, Any]] = {}
    for item in upstream_candidates:
        key = _window_key(item)
        candidate = dict(item)
        if candidate.get("selected") and key not in trace_keys:
            candidate = _unmatched_upstream_selected_to_discarded(candidate)
        by_key[key] = candidate
    for trace_candidate in trace_candidates:
        key = _window_key(trace_candidate)
        if key in by_key:
            merged = {**by_key[key]}
            merged.update({
                "draft_id": trace_candidate.get("draft_id"),
                "draft_name": trace_candidate.get("draft_name"),
                "selected": True,
                "discarded": False,
                "discard_cause": None,
                "selection_reason": trace_candidate.get("selection_reason") or "selected_for_uploaded_draft",
                "unmatched_selector_selection": False,
            })
            by_key[key] = merged
        else:
            by_key[key] = trace_candidate
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
        "unmatched_selector_selected_count": unmatched_selector_selected_count,
        "discard_causes_available": discard_causes_available,
        "recall_status": "selected_and_discarded" if selected_count > 0 and discard_causes_available else "selected_only",
        "known_gap": None if selected_count > 0 and discard_causes_available else "discarded candidates are not yet emitted by the upstream selector",
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
        f"recall_status={ledger['recall_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def _candidate_from_window(draft: dict[str, Any], idx: int, window: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(draft.get("draft_id") or draft.get("draft_name") or "unknown_draft")
    return {
        "candidate_id": _candidate_id(draft_id, idx, window),
        "draft_id": draft_id,
        "draft_name": draft.get("draft_name") or draft_id,
        "selected": True,
        "dropped": False,
        "dropped_reason": None,
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


def build_ledger(trace_path: Path) -> dict[str, Any]:
    trace = _read_json(trace_path)
    drafts = [draft for draft in trace.get("drafts", []) if isinstance(draft, dict)]
    candidates: list[dict[str, Any]] = []
    for draft in drafts:
        windows = [window for window in draft.get("source_windows", []) if isinstance(window, dict)]
        if not windows and isinstance(draft.get("source_window"), dict):
            windows = [draft["source_window"]]
        for idx, window in enumerate(windows):
            candidates.append(_candidate_from_window(draft, idx, window))
    selected_count = sum(1 for item in candidates if item.get("selected"))
    dropped_count = sum(1 for item in candidates if item.get("dropped"))
    return {
        "schema_version": "sportreel.candidate_decision_ledger.v1",
        "source": {
            "draft_decision_trace_path": str(trace_path),
            "source_trace_schema_version": trace.get("schema_version"),
        },
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "dropped_count": dropped_count,
        "dropped_reasons_present": dropped_count > 0 and all(item.get("dropped_reason") for item in candidates if item.get("dropped")),
        "recall_status": "selected_only" if selected_count > 0 and dropped_count == 0 else "selected_and_dropped",
        "known_gap": "dropped candidates are not yet emitted by the upstream selector" if selected_count > 0 and dropped_count == 0 else None,
        "candidates": candidates,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: build_candidate_decision_ledger.py DRAFT_DECISION_TRACE_JSON OUTPUT_JSON", file=sys.stderr)
        return 2
    ledger = build_ledger(Path(sys.argv[1]))
    _write_json(Path(sys.argv[2]), ledger)
    print(
        "candidate ledger "
        f"candidates={ledger['candidate_count']} "
        f"selected={ledger['selected_count']} "
        f"dropped={ledger['dropped_count']} "
        f"recall_status={ledger['recall_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

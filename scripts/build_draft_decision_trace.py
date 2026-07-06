#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

LONG_VIDEO_RE = re.compile(r"Long video:\s*(?P<name>.+)$")


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _source_from_log(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = LONG_VIDEO_RE.search(line)
        if match:
            return match.group("name").strip()
    return None


def _event_window(event: dict[str, Any], default_source: str | None) -> dict[str, Any]:
    start = event.get("start")
    end = event.get("end")
    return {
        "source_video": event.get("_src") or event.get("source_video") or default_source,
        "event_type": event.get("type", ""),
        "start": start,
        "end": end,
        "duration": (float(end) - float(start)) if isinstance(start, (int, float)) and isinstance(end, (int, float)) else None,
        "score": event.get("score"),
        "description": event.get("description", ""),
        "edit": event.get("edit", {}),
    }


def _draft_trace(draft_name: str, meta: dict[str, Any], default_source: str | None) -> dict[str, Any]:
    events = [e for e in meta.get("events", []) if isinstance(e, dict)]
    windows = [_event_window(event, default_source) for event in events]
    starts = [w["start"] for w in windows if isinstance(w.get("start"), (int, float))]
    ends = [w["end"] for w in windows if isinstance(w.get("end"), (int, float))]
    source_window = {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
        "source_video": next((w.get("source_video") for w in windows if w.get("source_video")), default_source),
    }
    return {
        "draft_id": draft_name,
        "draft_name": draft_name,
        "title": draft_name,
        "sport": meta.get("sport"),
        "qa_status": "review_required" if "QA-FLAGGED" in draft_name else "unknown",
        "review_required_reasons": ["QA-FLAGGED"] if "QA-FLAGGED" in draft_name else [],
        "source_window": source_window,
        "source_windows": windows,
        "events": events,
        "source_quality": meta.get("source_quality", {}),
    }


def build_trace(metadata_path: Path, log_path: Path) -> dict[str, Any]:
    metadata = _read_json(metadata_path) if metadata_path.exists() else {}
    if not isinstance(metadata, dict):
        metadata = {}
    default_source = _source_from_log(log_path)
    drafts = [
        _draft_trace(str(draft_name), meta, default_source)
        for draft_name, meta in sorted(metadata.items())
        if isinstance(meta, dict)
    ]
    return {
        "schema_version": "sportreel.draft_decision_trace.v1",
        "source": {
            "metadata_path": str(metadata_path),
            "log_path": str(log_path),
            "default_source_video": default_source,
        },
        "draft_count": len(drafts),
        "drafts": drafts,
    }


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_draft_decision_trace.py REELS_METADATA_JSON RUN_LOG OUTPUT_JSON", file=sys.stderr)
        return 2
    report = build_trace(Path(sys.argv[1]), Path(sys.argv[2]))
    _write_json(Path(sys.argv[3]), report)
    print(f"draft decision trace drafts={report['draft_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

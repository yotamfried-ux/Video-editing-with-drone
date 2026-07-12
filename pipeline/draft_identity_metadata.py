"""Persist athlete, chunk, source, and final-cut lineage for every draft event."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_INSTALL_FLAG = "_sportreel_draft_identity_metadata_installed"

_EVENT_KEYS = (
    "type", "score", "start", "end", "duration", "description", "edit",
    "person_id", "source_person_id", "chunk_person_id", "athlete_id",
    "athlete_canonical_key", "athlete_canonical_evidence_status", "athlete_duplicate_group",
    "track_id", "target_track_id", "primary_track_id",
    "source_video", "source", "_src",
    "chunk_index", "chunk_source_start", "chunk_source_end",
    "chunk_local_start", "chunk_local_end",
    "timestamp_encoding", "timestamp_basis", "timestamp_recovered", "timestamp_clamped",
    "raw_chunk_start", "raw_chunk_end", "interpreted_chunk_start", "interpreted_chunk_end",
    "original_start", "original_end", "selector_original_start", "selector_original_end",
    "final_cut_start", "final_cut_end", "cut_adjustment_reason",
    "window_validation_status", "window_validation_reason",
    "setup_start", "peak_time", "outcome_end", "selection_rescue", "qa_gate",
    "subject_isolation_gate", "multi_person_clip_gate",
    "_qa_reedit_allow_long_cut",
    "_qa_reedit_selector_start", "_qa_reedit_selector_end",
    "_qa_reedit_original_start", "_qa_reedit_original_end",
    "_qa_reedit_previous_start", "_qa_reedit_previous_end",
    "_qa_reedit_requested_end", "_qa_reedit_max_window_sec",
)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _EVENT_KEYS:
        if key in event and event.get(key) is not None:
            out[key] = _json_safe(event.get(key))
    source = out.get("_src") or out.get("source_video") or out.get("source")
    if source:
        out["source_video"] = Path(str(source)).name
        out["source_path"] = str(source)
    return out


def _unique(events: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for event in events:
        value = event.get(key)
        if value is None or not str(value).strip():
            continue
        text = str(value).strip()
        if text not in values:
            values.append(text)
    return values


def enrich_metadata_entry(entry: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    serialized = [serialize_event(event) for event in events if isinstance(event, dict)]
    person_ids = _unique(serialized, "person_id")
    athlete_ids = _unique(serialized, "athlete_id")
    chunk_person_ids = _unique(serialized, "chunk_person_id")
    source_videos = _unique(serialized, "source_video")
    enriched = dict(entry)
    enriched["events"] = serialized
    enriched["person_ids"] = person_ids
    enriched["athlete_ids"] = athlete_ids
    enriched["chunk_person_ids"] = chunk_person_ids
    enriched["source_videos"] = source_videos
    enriched["person_id"] = person_ids[0] if len(person_ids) == 1 else None
    enriched["athlete_id"] = athlete_ids[0] if len(athlete_ids) == 1 else None
    enriched["identity_lineage_status"] = (
        "complete"
        if serialized and all(event.get("person_id") and event.get("athlete_id") and event.get("source_video") for event in serialized)
        else "incomplete"
    )
    return enriched


def _rewrite_entry(meta_file: str, draft_name: str, events: list[dict[str, Any]]) -> None:
    try:
        with open(meta_file, encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    entry = metadata.get(draft_name) if isinstance(metadata.get(draft_name), dict) else {}
    metadata[draft_name] = enrich_metadata_entry(entry, events)
    tmp = meta_file + ".identity.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_file)


def install() -> None:
    import config
    import pipeline.orchestrator as orchestrator

    if getattr(orchestrator, _INSTALL_FLAG, False):
        return
    original = orchestrator._save_reel_metadata

    def save_with_identity(draft_name: str, sport: str, events: list[dict[str, Any]], source_quality: dict) -> None:
        original(draft_name, sport, events, source_quality)
        try:
            _rewrite_entry(config.REEL_METADATA_FILE, draft_name, events)
        except Exception as exc:
            orchestrator.logger.warning("Failed to persist identity lineage for %s: %s", draft_name, exc)

    orchestrator._save_reel_metadata = save_with_identity
    setattr(orchestrator, _INSTALL_FLAG, True)

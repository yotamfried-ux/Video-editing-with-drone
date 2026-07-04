"""Per-draft diagnostic artifact for PQ-010."""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import os
import sys
from typing import Any

REQUIRED_SECTIONS = [
    "source_videos",
    "raw_gemini_events",
    "perception_tracks",
    "identity_clusters",
    "ordered_events",
    "dropped_events",
    "qa",
    "final_upload_key",
]

_INSTALLED_FLAG = "_sportreel_draft_diagnostics_installed"
_FINDER_FLAG = "_sportreel_draft_diagnostics_import_hook_installed"


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items() if not str(k).startswith("_") or str(k) in {"_src", "_teaser", "_is_climax"}}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _source_videos(events: list[dict[str, Any]], source_quality: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for event in events:
        src = event.get("_src") or event.get("source") or event.get("source_video") or event.get("video")
        if src:
            seen.setdefault(str(src), {"path": str(src), "name": os.path.basename(str(src))})
    if not seen:
        name = source_quality.get("name") or source_quality.get("path") or source_quality.get("source") or "unknown"
        seen[str(name)] = {"path": str(name), "name": os.path.basename(str(name))}
    for source in seen.values():
        source["quality"] = _clean(source_quality)
    return list(seen.values())


def _raw_gemini_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for idx, event in enumerate(events):
        out.append({
            "event_id": _event_id(event, idx),
            "type": event.get("type", ""),
            "score": event.get("score"),
            "start": event.get("original_start", event.get("start")),
            "end": event.get("original_end", event.get("end")),
            "description": event.get("description", ""),
            "crop_x": event.get("crop_x"),
            "crop_y": event.get("crop_y"),
        })
    return out


def _perception_tracks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tracks = []
    for idx, event in enumerate(events):
        tracks.append({
            "event_id": _event_id(event, idx),
            "track_id": event.get("track_id"),
            "bbox_xyxy": event.get("bbox_xyxy"),
            "confidence": event.get("perception_confidence") or event.get("confidence"),
            "visible_ratio": event.get("visible_ratio"),
            "crop_source": event.get("crop_source"),
            "window_status": event.get("window_validation_status"),
        })
    return tracks


def _identity_clusters(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members = []
    for idx, event in enumerate(events):
        members.append({
            "event_id": _event_id(event, idx),
            "person_id": event.get("person_id") or event.get("athlete_id"),
            "identity_confidence": event.get("identity_confidence"),
            "mixed_athlete": event.get("mixed_athlete"),
            "identity_mismatch": event.get("identity_mismatch"),
        })
    return [{"cluster_id": "draft_cluster", "members": members}]


def _ordered_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = []
    for idx, event in enumerate(events):
        ordered.append({
            "order": idx,
            "event_id": _event_id(event, idx),
            "type": event.get("type", ""),
            "score": event.get("score"),
            "quality_score": event.get("quality_score"),
            "start": event.get("start"),
            "end": event.get("end"),
            "final_cut_start": event.get("final_cut_start"),
            "final_cut_end": event.get("final_cut_end"),
            "cut_adjustment_reason": event.get("cut_adjustment_reason"),
            "is_teaser": bool(event.get("_teaser")),
            "is_climax": bool(event.get("_is_climax")),
            "edit": _clean(event.get("edit", {})),
        })
    return ordered


def _dropped_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dropped: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        for duplicate in event.get("dedup_dropped_duplicates", []) or []:
            dropped.append({"event_id": _event_id(event, idx), "reason": "duplicate_moment", "detail": _clean(duplicate)})
        qa_gate = event.get("qa_gate")
        if isinstance(qa_gate, dict):
            for defect in qa_gate.get("defects", []) or []:
                if defect.get("blocking"):
                    dropped.append({"event_id": defect.get("event_id") or _event_id(event, idx), "reason": defect.get("type", "QA_DEFECT"), "detail": _clean(defect)})
    return dropped


def _qa(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in events:
        qa_gate = event.get("qa_gate")
        if isinstance(qa_gate, dict):
            return _clean(qa_gate)
    return {"decision": "not_flagged", "final_verdict": "PASS_OR_NOT_RUN", "retry_count": 0, "defects": []}


def build_diagnostic_artifact(draft_name: str, sport: str, events: list[dict[str, Any]], source_quality: dict[str, Any], final_upload_key: str | None = None) -> dict[str, Any]:
    artifact = {
        "schema_version": "1.0",
        "draft_name": draft_name,
        "sport": sport,
        "source_videos": _source_videos(events, source_quality),
        "raw_gemini_events": _raw_gemini_events(events),
        "perception_tracks": _perception_tracks(events),
        "identity_clusters": _identity_clusters(events),
        "ordered_events": _ordered_events(events),
        "dropped_events": _dropped_events(events),
        "qa": _qa(events),
        "final_upload_key": final_upload_key or draft_name,
    }
    missing = [section for section in REQUIRED_SECTIONS if section not in artifact]
    if missing:
        raise ValueError(f"diagnostic artifact missing sections: {missing}")
    return artifact


def augment_metadata_entry(meta_file: str, draft_name: str, artifact: dict[str, Any]) -> None:
    try:
        with open(meta_file, encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = {}
    entry = metadata.setdefault(draft_name, {})
    entry["diagnostic_artifact"] = artifact
    tmp = meta_file + ".diag.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_file)


def _patch_orchestrator(orchestrator: Any) -> None:
    import config
    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return
    original_save_metadata = orchestrator._save_reel_metadata

    def save_metadata_with_diagnostics(draft_name, sport, events, source_quality):
        original_save_metadata(draft_name, sport, events, source_quality)
        artifact = build_diagnostic_artifact(draft_name, sport, events, source_quality, final_upload_key=draft_name)
        augment_metadata_entry(config.REEL_METADATA_FILE, draft_name, artifact)

    orchestrator._save_reel_metadata = save_metadata_with_diagnostics
    setattr(orchestrator, _INSTALLED_FLAG, True)


class _DraftDiagnosticsLoader(importlib.abc.Loader):
    def __init__(self, loader: importlib.abc.Loader):
        self.loader = loader

    def create_module(self, spec):
        create = getattr(self.loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module) -> None:
        self.loader.exec_module(module)
        _patch_orchestrator(module)


class _DraftDiagnosticsFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "pipeline.orchestrator":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _DraftDiagnosticsLoader(spec.loader)
        return spec


def install() -> None:
    module = sys.modules.get("pipeline.orchestrator")
    if module is not None:
        _patch_orchestrator(module)
        return
    if getattr(sys, _FINDER_FLAG, False):
        return
    sys.meta_path.insert(0, _DraftDiagnosticsFinder())
    setattr(sys, _FINDER_FLAG, True)

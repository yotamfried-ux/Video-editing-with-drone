"""Per-draft diagnostic artifact for PQ-010."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REQUIRED_SECTIONS = ["source_videos", "raw_gemini_events", "perception_tracks", "identity_clusters", "ordered_events", "dropped_events", "qa", "final_upload_key"]
_INSTALLED_FLAG = "_sportreel_draft_diagnostics_installed"
_QA_WRAPPED = "_sportreel_draft_diagnostics_wrapped_qa"


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_diagnostic_artifact(draft_name: str, sport: str, events: list[dict[str, Any]], source_quality: dict[str, Any], final_upload_key: str | None = None) -> dict[str, Any]:
    sources = []
    seen = set()
    for event in events:
        src = event.get("_src") or event.get("source") or event.get("source_video") or event.get("video")
        if src and src not in seen:
            seen.add(src)
            sources.append({"path": str(src), "name": os.path.basename(str(src)), "quality": _clean(source_quality)})
    if not sources:
        sources.append({"path": "unknown", "name": "unknown", "quality": _clean(source_quality)})

    raw_events = []
    tracks = []
    ordered = []
    dropped = []
    qa = {"decision": "not_flagged", "final_verdict": "PASS_OR_NOT_RUN", "retry_count": 0, "defects": []}
    identity_members = []
    for idx, event in enumerate(events):
        eid = _event_id(event, idx)
        identity_gate = _clean(event.get("identity_gate")) if isinstance(event.get("identity_gate"), dict) else None
        multi_person_gate = _clean(event.get("multi_person_clip_gate")) if isinstance(event.get("multi_person_clip_gate"), dict) else None
        cut_guard = {
            "status": event.get("cut_window_evidence_status"),
            "reason": event.get("cut_window_guard_reason"),
            "original_end_before_guard": event.get("original_end_before_cut_guard"),
            "window_uncertain": event.get("window_uncertain"),
        } if event.get("cut_window_evidence_status") else None
        raw_events.append({"event_id": eid, "type": event.get("type", ""), "score": event.get("score"), "start": event.get("original_start", event.get("start")), "end": event.get("original_end", event.get("end")), "description": event.get("description", "")})
        tracks.append({"event_id": eid, "track_id": event.get("track_id"), "bbox_xyxy": event.get("bbox_xyxy"), "confidence": event.get("perception_confidence") or event.get("confidence"), "visible_ratio": event.get("visible_ratio")})
        identity_members.append({"event_id": eid, "person_id": event.get("person_id") or event.get("athlete_id"), "identity_confidence": event.get("identity_confidence"), "identity_mismatch": event.get("identity_mismatch"), "identity_gate": identity_gate, "multi_person_clip_gate": multi_person_gate})
        ordered.append({"order": idx, "event_id": eid, "type": event.get("type", ""), "score": event.get("score"), "start": event.get("start"), "end": event.get("end"), "final_cut_start": event.get("final_cut_start"), "final_cut_end": event.get("final_cut_end"), "cut_adjustment_reason": event.get("cut_adjustment_reason"), "cut_window_guard": cut_guard, "is_teaser": bool(event.get("_teaser")), "is_climax": bool(event.get("_is_climax")), "identity_gate": identity_gate, "multi_person_clip_gate": multi_person_gate})
        for duplicate in event.get("dedup_dropped_duplicates", []) or []:
            dropped.append({"event_id": eid, "reason": "duplicate_moment", "detail": _clean(duplicate)})
        if identity_gate and identity_gate.get("decision") == "split_to_single_appearance":
            dropped.append({"event_id": eid, "reason": identity_gate.get("reason", "identity_gate"), "detail": identity_gate})
        if multi_person_gate and multi_person_gate.get("decision") == "review_required":
            dropped.append({"event_id": eid, "reason": "MULTI_PERSON_CLIP", "detail": multi_person_gate})
        if isinstance(event.get("qa_gate"), dict):
            qa = _clean(event["qa_gate"])
            for defect in qa.get("defects", []) or []:
                if defect.get("blocking"):
                    dropped.append({"event_id": defect.get("event_id") or eid, "reason": defect.get("type", "QA_DEFECT"), "detail": _clean(defect)})

    artifact = {"schema_version": "1.0", "draft_name": draft_name, "sport": sport, "source_videos": sources, "raw_gemini_events": raw_events, "perception_tracks": tracks, "identity_clusters": [{"cluster_id": "draft_cluster", "members": identity_members}], "ordered_events": ordered, "dropped_events": dropped, "qa": qa, "final_upload_key": final_upload_key or draft_name}
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
    metadata.setdefault(draft_name, {})["diagnostic_artifact"] = artifact
    tmp = meta_file + ".diag.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_file)


def _patch_orchestrator(orchestrator: Any) -> None:
    import config
    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return
    original = orchestrator._save_reel_metadata

    def save_with_diagnostics(draft_name, sport, events, source_quality):
        original(draft_name, sport, events, source_quality)
        artifact = build_diagnostic_artifact(draft_name, sport, events, source_quality, final_upload_key=draft_name)
        augment_metadata_entry(config.REEL_METADATA_FILE, draft_name, artifact)

    orchestrator._save_reel_metadata = save_with_diagnostics
    setattr(orchestrator, _INSTALLED_FLAG, True)


def _wrap_qa_hook() -> bool:
    qa_policy = sys.modules.get("pipeline.qa_gate_policy")
    if qa_policy is None or getattr(qa_policy, _QA_WRAPPED, False):
        return False
    original = getattr(qa_policy, "_patch_orchestrator", None)
    if original is None:
        return False

    def patch_both(orchestrator: Any) -> None:
        original(orchestrator)
        _patch_orchestrator(orchestrator)

    qa_policy._patch_orchestrator = patch_both
    setattr(qa_policy, _QA_WRAPPED, True)
    return True


def install() -> None:
    module = sys.modules.get("pipeline.orchestrator")
    if module is not None:
        _patch_orchestrator(module)
        return
    if _wrap_qa_hook():
        return
    import pipeline.qa_gate_policy as qa_policy
    qa_policy.install()
    _wrap_qa_hook()

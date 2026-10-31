"""Versioned export of what the pipeline *predicted* (``predictions/v1``).

Pure conversion of artifacts the pipeline already writes — the candidate decision ledger
(``sportreel.candidate_decision_ledger.v1``) and the per-reel EDL files (``edl/v1``) — into the structure consumed by
Annotation Studio's blind evaluator. It performs no inference, reads no ground truth, and carries the run id and code
commit so every prediction is traceable. Events are exported in the source video's own time base (seconds, plus frames
when the source frame rate is known).
"""
from __future__ import annotations

import os
import hashlib
import json
import math
from collections import defaultdict
from typing import Any

PREDICTIONS_SCHEMA = "predictions/v1"
EXPORTER_VERSION = "1.0.0"


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _source_index(edls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """filename -> {sha256, fps, width, height}, from the shots that were actually rendered."""
    index: dict[str, dict[str, Any]] = {}
    for edl in edls:
        for shot in edl.get("shots", []):
            name = shot.get("source_file")
            if name and shot.get("source_sha256"):
                src = shot.get("source") or {}
                index[name] = {"sha256": shot["source_sha256"], "fps": src.get("fps"),
                               "width": src.get("width"), "height": src.get("height")}
    return index


def _frames(start: float, end: float, fps: float | None) -> dict[str, int]:
    """Half-open [start_frame, end_frame): floor the start, ceil the end (never shrink an event)."""
    if not fps:
        return {}
    return {"start_frame": int(math.floor(start * fps + 1e-6)), "end_frame": int(math.ceil(end * fps - 1e-6))}


def _outputs_for(name: str, start: float, end: float, edls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Which rendered outputs show this source window (lineage output -> source)."""
    found = []
    for edl in edls:
        fps = edl.get("output", {}).get("fps") or 30
        for shot in edl.get("shots", []):
            if shot.get("source_file") != name:
                continue
            src_fps = (shot.get("source") or {}).get("fps") or fps
            s0 = shot["src_start"] / src_fps
            s1 = s0 + (shot["out_end"] - shot["out_start"]) * (shot.get("speed") or 1) / src_fps
            if min(s1, end) > max(s0, start):
                found.append({"output_id": edl["output_id"], "out_start": shot["out_start"], "out_end": shot["out_end"],
                              "event_id": shot.get("event_id"), "mode": shot.get("mode"), "track_id": shot.get("track_id")})
    return sorted(found, key=lambda o: (o["output_id"], o["out_start"]))


def build_predictions(
    ledger: dict[str, Any],
    edls: list[dict[str, Any]],
    *,
    run_id: str | None,
    commit: str | None,
    source_hashes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``source_hashes`` (filename -> {sha256, fps}) fills in sources that were never rendered (rejected candidates)."""
    index = {**(source_hashes or {}), **_source_index(edls)}
    by_source: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for cand in ledger.get("candidates", []):
        window = cand.get("source_window") or {}
        start, end = _num(window.get("start")), _num(window.get("end"))
        name = cand.get("source_video")
        if not name or start is None or end is None or end <= start:
            unresolved.append({"candidate_id": cand.get("candidate_id"), "reason": "missing_source_or_window"})
            continue
        info = index.get(name)
        if not info or not info.get("sha256"):
            unresolved.append({"candidate_id": cand.get("candidate_id"), "source_video": name, "reason": "source_sha256_unknown"})
            continue
        decision = "selected" if cand.get("selected") else "rejected"
        entry = by_source.setdefault(info["sha256"], {"source_sha256": info["sha256"], "source_video": name,
                                                       "fps": info.get("fps"), "events": [], "tracks": {}})
        event = {
            "candidate_id": cand.get("candidate_id"),
            "event_type": cand.get("event_type") or None,
            "start_sec": round(start, 3), "end_sec": round(end, 3),
            **_frames(start, end, info.get("fps")),
            "athlete_key": cand.get("athlete_id") or cand.get("person_id") or cand.get("athlete_canonical_key"),
            "person_id": cand.get("person_id"),
            "decision": decision,
            "reason": cand.get("selection_reason") if decision == "selected" else cand.get("discard_cause"),
            "score": cand.get("score"),
            "evidence": {k: cand.get(k) for k in ("athlete_canonical_evidence_status", "identity_lineage_status", "timestamp_basis")
                         if cand.get(k) is not None},
            "outputs": _outputs_for(name, start, end, edls) if decision == "selected" else [],
        }
        # Sport is declared, never inferred: per-candidate if the ledger carries it, else the operator-set SPORTREEL_SPORT.
        sport = cand.get("sport_id") or os.environ.get("SPORTREEL_SPORT")
        if sport:
            event["sport_id"] = str(sport)
        entry["events"].append(event)
    # tracks come from the EDL's recorded subject tracks (existing perception evidence, thinned)
    for edl in edls:
        for shot in edl.get("shots", []):
            sha, tid, samples = shot.get("source_sha256"), shot.get("track_id"), shot.get("subject_track")
            if sha in by_source and tid is not None and samples:
                by_source[sha]["tracks"].setdefault(str(tid), {}).update({d["src_frame"]: d for d in samples})
    sources = []
    for sha in sorted(by_source):
        entry = by_source[sha]
        entry["events"].sort(key=lambda e: (e["start_sec"], e["end_sec"], str(e["candidate_id"])))
        entry["tracks"] = [{"track_id": tid, "samples": [samples[f] for f in sorted(samples)]}
                           for tid, samples in sorted(entry["tracks"].items())]
        sources.append(entry)
    payload = {
        "schema": PREDICTIONS_SCHEMA,
        "exporter_version": EXPORTER_VERSION,
        "run_id": run_id or "unknown",
        "pipeline_commit": commit or "unknown",
        "pipeline_version": (commit or "unknown")[:12],
        "inputs": {"candidate_ledger_schema": ledger.get("schema_version"),
                   "candidate_ledger_digest": canonical_digest(ledger),
                   "edl_digests": sorted(canonical_digest(e) for e in edls)},
        "recall_status": ledger.get("recall_status"),
        "known_gap": ledger.get("known_gap"),
        "athletes": ledger.get("detected_athlete_registry", []),
        "sources": sources,
        "outputs": sorted(({"output_id": e["output_id"], "pipeline_commit": e.get("pipeline_commit"), "mapping": e.get("mapping")} for e in edls),
                          key=lambda o: o["output_id"]),
        "unresolved": unresolved,
    }
    payload["digest"] = canonical_digest(payload)
    return payload


def validate_predictions(payload: dict[str, Any]) -> list[str]:
    """Contract check used by tests and by Studio's importer (mirrored there)."""
    problems: list[str] = []
    if payload.get("schema") != PREDICTIONS_SCHEMA:
        problems.append("schema")
    for key in ("run_id", "pipeline_commit"):
        if not payload.get(key) or payload[key] == "unknown":
            problems.append(f"{key}_unknown")
    for src in payload.get("sources", []):
        if len(str(src.get("source_sha256", ""))) != 64:
            problems.append("bad_source_sha256")
        for ev in src.get("events", []):
            if ev.get("decision") not in {"selected", "rejected"}:
                problems.append("bad_decision")
            if not ev["end_sec"] > ev["start_sec"]:
                problems.append("bad_interval")
    return problems

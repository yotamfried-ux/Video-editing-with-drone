"""Deterministic incremental cache for rendered reels and QA approvals (OPT-07).

Provides content-addressed caching for:
  1. Rendered reels (`.mp4` + event lineage), keyed by source video SHA-256s,
     trim windows, editing decisions, FFmpeg parameters, and code version.
  2. Final QA results, keyed by the exact SHA-256 of the rendered `.mp4` file,
     event/identity evidence signature, and QA policy version.

Safety invariants:
  - Any change to the rendered video bytes, trim windows, athlete identity, or
    QA policy automatically invalidates the QA cache (Cache Miss).
  - All cache writes use atomic temp-file + `os.replace` under a lock so concurrent
    threads never corrupt cache entries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping

from integrations import llm_cache as _llm_cache

logger = logging.getLogger(__name__)

RENDER_CODE_VERSION = "render-v2"
QA_POLICY_VERSION = "qa-policy-v2"
_CACHE_LOCK = threading.RLock()


def cache_enabled() -> bool:
    return os.getenv("SPORTREEL_RENDER_QA_CACHE", "1").strip().lower() not in {"0", "false", "no", "off"}


def _cache_root() -> Path:
    configured = os.getenv("SPORTREEL_RENDER_QA_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    llm_dir = os.getenv("LLM_CACHE_DIR", "").strip()
    if llm_dir:
        return Path(llm_dir) / "render_qa_cache"
    return Path(os.getenv("TMP_DIR", "/tmp/dtor")) / ".render_qa_cache"


def _source_signature(video_path: str) -> str:
    if not video_path:
        return "missing"
    if os.path.exists(video_path):
        try:
            return _llm_cache.file_sha256(video_path)
        except Exception:
            pass
    return f"path:{Path(str(video_path)).name}"


def _canonical_event_spec(ev: Mapping[str, Any]) -> dict[str, Any]:
    edit = ev.get("edit") if isinstance(ev.get("edit"), Mapping) else {}
    return {
        "src": Path(str(ev.get("_src") or ev.get("source") or ev.get("source_video") or "")).name,
        "type": str(ev.get("type") or ""),
        "start": round(float(ev.get("start") or 0.0), 3),
        "end": round(float(ev.get("end") or 0.0), 3),
        "setup_start": ev.get("setup_start"),
        "peak_time": ev.get("peak_time"),
        "outcome_end": ev.get("outcome_end"),
        "final_cut_start": ev.get("final_cut_start"),
        "final_cut_end": ev.get("final_cut_end"),
        "score": ev.get("score"),
        "crop_x": round(float(ev.get("crop_x") if ev.get("crop_x") is not None else 0.5), 4),
        "crop_y": round(float(ev.get("crop_y") if ev.get("crop_y") is not None else 0.65), 4),
        "bbox_xyxy": [round(float(v), 2) for v in (ev.get("bbox_xyxy") or [])] if isinstance(ev.get("bbox_xyxy"), (list, tuple)) else None,
        "track_id": str(ev.get("target_track_id") or ev.get("track_id") or ""),
        "source_person_key": str(ev.get("source_person_key") or ""),
        "athlete_id": str(ev.get("athlete_id") or ""),
        "edit": {
            "zoom": round(float(edit.get("zoom") or 1.0), 3),
            "slowmo": bool(edit.get("slowmo", False)),
            "focus": str(edit.get("focus") or "peak"),
            "transition_out": str(edit.get("transition_out") or "slide"),
        },
    }


def compute_render_signature(
    appearances: list[dict[str, Any]],
    *,
    sport: str = "",
    athlete_label: str = "",
    ffmpeg_params: Mapping[str, Any] | None = None,
    code_version: str = RENDER_CODE_VERSION,
) -> str:
    """Compute a deterministic SHA-256 cache key for a multi-source reel render."""
    normalized_apps = []
    for app in appearances or []:
        if not isinstance(app, Mapping):
            continue
        path = str(app.get("path") or "")
        events = [
            _canonical_event_spec(ev)
            for ev in (app.get("events") or [])
            if isinstance(ev, Mapping) and not ev.get("_teaser")
        ]
        normalized_apps.append({
            "source_sig": _source_signature(path),
            "source_name": Path(path).name if path else "",
            "events": events,
        })
    payload = {
        "kind": "sportreel_render_cache_v1",
        "code_version": code_version,
        "one_reel_per_athlete": os.getenv("SPORTREEL_ONE_REEL_PER_ATHLETE", "1").strip().lower(),
        "sport": str(sport or "").strip().lower(),
        "athlete_label": str(athlete_label or "").strip(),
        "ffmpeg_params": dict(ffmpeg_params or {"codec": "libx264", "aspect": "9:16", "silent": True}),
        "appearances": normalized_apps,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def get_cached_render(
    render_signature: str,
    dest_mp4_path: str,
) -> tuple[bool, list[dict[str, Any]] | None]:
    """Restore a cached rendered `.mp4` and its event lineage to `dest_mp4_path` if valid."""
    if not cache_enabled() or not render_signature:
        return False, None
    root = _cache_root() / "renders"
    cached_mp4 = root / f"{render_signature}.mp4"
    cached_meta = root / f"{render_signature}.json"
    with _CACHE_LOCK:
        if not cached_mp4.exists() or not cached_meta.exists():
            return False, None
        try:
            meta = json.loads(cached_meta.read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("render_signature") != render_signature:
                return False, None
            expected_sha = meta.get("mp4_sha256")
            actual_sha = _llm_cache.file_sha256(str(cached_mp4))
            if not expected_sha or expected_sha != actual_sha:
                logger.warning("Corrupt render cache entry %s (sha256 mismatch); invalidating", render_signature[:12])
                return False, None
            dest = Path(dest_mp4_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_dest = dest.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp.mp4")
            shutil.copy2(cached_mp4, tmp_dest)
            os.replace(tmp_dest, dest)
            events = copy.deepcopy(meta.get("events") or [])
            return True, events
        except Exception as exc:
            logger.debug("Render cache read skipped for %s: %s", render_signature[:12], exc)
            return False, None


def put_cached_render(
    render_signature: str,
    rendered_mp4_path: str,
    events: list[dict[str, Any]],
) -> bool:
    """Atomically store a rendered `.mp4` and its event lineage in the render cache."""
    if not cache_enabled() or not render_signature or not os.path.exists(rendered_mp4_path):
        return False
    root = _cache_root() / "renders"
    with _CACHE_LOCK:
        try:
            root.mkdir(parents=True, exist_ok=True)
            mp4_sha = _llm_cache.file_sha256(rendered_mp4_path)
            cached_mp4 = root / f"{render_signature}.mp4"
            cached_meta = root / f"{render_signature}.json"
            uid = uuid.uuid4().hex[:8]
            tmp_mp4 = root / f"{render_signature}.{uid}.tmp.mp4"
            tmp_meta = root / f"{render_signature}.{uid}.tmp.json"

            shutil.copy2(rendered_mp4_path, tmp_mp4)
            meta_payload = {
                "render_signature": render_signature,
                "mp4_sha256": mp4_sha,
                "events": copy.deepcopy(events),
            }
            tmp_meta.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_mp4, cached_mp4)
            os.replace(tmp_meta, cached_meta)
            return True
        except Exception as exc:
            logger.debug("Render cache write skipped for %s: %s", render_signature[:12], exc)
            return False


def compute_qa_signature(
    reel_path: str,
    *,
    events: list[dict[str, Any]] | None = None,
    sport: str = "",
    athlete_label: str = "",
    qa_policy_version: str = QA_POLICY_VERSION,
) -> str | None:
    """Compute an exact SHA-256 QA signature bound to the rendered reel's bytes, EDL, and policy."""
    if not reel_path or not os.path.exists(reel_path):
        return None
    try:
        reel_sha = _llm_cache.file_sha256(reel_path)
    except Exception:
        return None
    canonical_events = [
        _canonical_event_spec(ev)
        for ev in (events or [])
        if isinstance(ev, Mapping) and not ev.get("_teaser")
    ]
    # Strip injected EDIT_SOURCE_CONTEXT_JSON suffix from athlete_label and hash it explicitly
    clean_label = str(athlete_label or "").split("\nEDIT_SOURCE_CONTEXT_JSON:")[0].strip()
    payload = {
        "kind": "sportreel_qa_cache_v1",
        "qa_policy_version": qa_policy_version,
        "engagement_threshold": int(os.getenv("QA_ENGAGEMENT_THRESHOLD", "60")),
        "one_reel_per_athlete": os.getenv("SPORTREEL_ONE_REEL_PER_ATHLETE", "1").strip().lower(),
        "reel_file_sha256": reel_sha,
        "sport": str(sport or "").strip().lower(),
        "athlete_label": clean_label,
        "events": canonical_events,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def get_cached_qa_result(qa_signature: str | None) -> dict[str, Any] | None:
    """Retrieve a cached QA result only if its cryptographic signature matches exactly."""
    if not cache_enabled() or not qa_signature:
        return None
    path = (_cache_root() / "qa") / f"{qa_signature}.json"
    with _CACHE_LOCK:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("qa_signature") != qa_signature:
                return None
            result = payload.get("result")
            if not isinstance(result, dict) or result.get("verdict") not in {"PASS", "FAIL"}:
                return None
            return {**copy.deepcopy(result), "qa_cache_hit": True, "qa_signature": qa_signature}
        except Exception:
            return None


def put_cached_qa_result(qa_signature: str | None, result: Mapping[str, Any]) -> bool:
    """Atomically persist a real QA result bound to `qa_signature`."""
    if not cache_enabled() or not qa_signature or not isinstance(result, Mapping):
        return False
    verdict = str(result.get("verdict") or "").upper()
    overall = str(result.get("overall") or "").strip().lower()
    if verdict not in {"PASS", "FAIL"} or overall == "qa skipped":
        return False
    defects = result.get("defects") or []
    if any(isinstance(d, Mapping) and str(d.get("code") or d.get("type") or "") in {"QA_PROVIDER_UNAVAILABLE", "QA_UNAVAILABLE"} for d in defects):
        return False

    root = _cache_root() / "qa"
    with _CACHE_LOCK:
        try:
            root.mkdir(parents=True, exist_ok=True)
            target = root / f"{qa_signature}.json"
            tmp = root / f"{qa_signature}.{uuid.uuid4().hex[:8]}.tmp.json"
            stored = {
                "qa_signature": qa_signature,
                "result": copy.deepcopy(dict(result)),
            }
            tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, target)
            return True
        except Exception as exc:
            logger.debug("QA cache write skipped for %s: %s", qa_signature[:12], exc)
            return False


__all__ = [
    "QA_POLICY_VERSION",
    "RENDER_CODE_VERSION",
    "cache_enabled",
    "compute_qa_signature",
    "compute_render_signature",
    "get_cached_qa_result",
    "get_cached_render",
    "put_cached_qa_result",
    "put_cached_render",
]

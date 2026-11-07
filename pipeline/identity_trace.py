"""Per-layer identity trace: which detected person ended up in which athlete, at every identity layer.

Observational only. It records what the pipeline decided and never reads ground truth, so measuring identity quality
(scripts/eval_identity_trace.py, run outside the pipeline against the operator's catalog) cannot leak labels back in.

Every detected person is keyed ``<source filename>::<person id>``; the key is stamped on each of the person's events
(``source_person_key``) so it survives every later copy of the event. Layers, in order:

  persons       every detected person handed to identity clustering (with its identity evidence)
  model         the clustering model's grouping (before safety passes)
  post_process  after impossible-cluster splits, duplicate merges and the visual verifier
  compile       what the reel compiler receives, after canonicalization and the real identity gate

The trace is written to ``$TMP_DIR/identity_trace.json`` after every record, so a run that dies still leaves it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = "sportreel.identity_trace.v1"
KEY_FIELD = "source_person_key"
LAYERS = ("model", "post_process", "compile")

_lock = threading.Lock()
_trace: dict[str, Any] = {"schema": SCHEMA, "persons": {}, "layers": {}}


def person_key(video_path: str, person_id: Any) -> str:
    return f"{Path(str(video_path or '')).name}::{str(person_id or '').strip()}"


def stamp_person(person: dict, video_path: str) -> dict:
    """Return the person with its source key on every event (input untouched)."""
    key = person_key(video_path, person.get("id"))
    return {**person, "events": [{**ev, KEY_FIELD: ev.get(KEY_FIELD) or key} for ev in person.get("events", []) or []]}


def _num(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _keys_of(cluster: dict) -> list[str]:
    keys: set[str] = set()
    for app in cluster.get("appearances", []) or []:
        for ev in app.get("events", []) or []:
            if ev.get(KEY_FIELD):
                keys.add(str(ev[KEY_FIELD]))
        if not any(ev.get(KEY_FIELD) for ev in app.get("events", []) or []) and app.get("_person_id"):
            keys.add(person_key(app.get("path", ""), app.get("_person_id")))
    return sorted(keys)


def _write() -> None:
    try:
        import config
        out = Path(getattr(config, "TMP_DIR", None) or os.getenv("TMP_DIR") or "/tmp") / "identity_trace.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(_trace, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as exc:  # observational: never break a run
        logger.debug("identity trace not written: %s", exc)


def record_persons(clip_analyses: list[dict]) -> None:
    try:
        with _lock:
            for ca in clip_analyses or []:
                path = ca.get("path", "")
                for person in (ca.get("analysis") or {}).get("persons", []) or []:
                    events = person.get("events") or []
                    if not events:
                        continue
                    key = person_key(path, person.get("id"))
                    for ev in events:
                        if isinstance(ev, dict) and not ev.get(KEY_FIELD):
                            ev[KEY_FIELD] = key
                    _trace["persons"][key] = {
                        "source": Path(str(path)).name,
                        "person_id": str(person.get("id", "")),
                        "description": str(person.get("description", ""))[:160],
                        "windows": [[_num(ev.get("start")), _num(ev.get("end"))] for ev in events],
                        "track_ids": sorted({str(ev.get("target_track_id") or ev.get("track_id"))
                                             for ev in events if (ev.get("target_track_id") or ev.get("track_id")) is not None}),
                        "track_binding": sorted({str(ev.get("track_binding_source")) for ev in events if ev.get("track_binding_source")}),
                        "evidence": person.get("identity_evidence") or {"kind": "crop_point_thumbnail" if person.get("thumbnail") else "none"},
                    }
            _write()
    except Exception as exc:
        logger.debug("identity trace persons skipped: %s", exc)


def record_layer(layer: str, clusters: list[dict]) -> None:
    try:
        rows = []
        for index, cluster in enumerate(clusters or []):
            rows.append({
                "cluster": index,
                "description": str(cluster.get("description", ""))[:120],
                "confidence": cluster.get("confidence") or cluster.get("_confidence"),
                "members": _keys_of(cluster),
                "flags": {k: cluster[k] for k in ("_visual_verified", "_identity_gate", "_identity_gate_reason") if cluster.get(k)},
            })
        with _lock:
            _trace["layers"][layer] = rows
            _write()
    except Exception as exc:
        logger.debug("identity trace layer %s skipped: %s", layer, exc)


def record_metadata(section: str, data: Any) -> None:
    """Record OPT-02 visual embedding pre-filter or OPT-03 decision engine traces."""
    try:
        with _lock:
            _trace[section] = data
            _write()
    except Exception as exc:
        logger.debug("identity trace metadata %s skipped: %s", section, exc)


def snapshot() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_trace))


def reset() -> None:
    with _lock:
        _trace["persons"].clear()
        _trace["layers"].clear()


def compact_lines(trace: dict[str, Any]) -> list[str]:
    """One line per person: where it went at each layer (for the job log)."""
    where: dict[str, dict[str, int]] = {}
    for layer in LAYERS:
        for row in trace.get("layers", {}).get(layer, []):
            for key in row.get("members", []):
                where.setdefault(key, {})[layer] = row["cluster"]
    lines = []
    for key in sorted(set(trace.get("persons", {})) | set(where)):
        p = trace.get("persons", {}).get(key, {})
        hops = " ".join(f"{layer}={where.get(key, {}).get(layer, '-')}" for layer in LAYERS)
        ev = (p.get("evidence") or {})
        lines.append(f"{key[-40:]:40} tracks={','.join(p.get('track_ids', [])) or '-':8} "
                     f"evidence={ev.get('kind', '-')}x{ev.get('crops', 1 if ev.get('kind') == 'crop_point_thumbnail' else 0)} {hops}")
    return lines

"""Test helper: give a fixture event the evidence a real production event carries.

pipeline.output_qualification withholds any shot without measured evidence (tracker binding, CV activity of the
target track, the validated actor span, a canonical event id and a content-addressed source). Fixtures that test
other properties of a *publishable* reel must therefore describe such a shot, the way the production analyzer
and perception stages produce it; this adds only fields that are missing.
"""
from __future__ import annotations

import hashlib
from typing import Any


def qualified(event: dict[str, Any], *, source: str = "fixture.mp4", track: str = "7") -> dict[str, Any]:
    start = float(event.get("start", 0.0))
    end = float(event.get("end", start + 5.0))
    ref = "sha256:" + hashlib.sha256(str(event.get("_src") or event.get("source_video") or source).encode()).hexdigest()
    uid = event.get("event_uid") or "ev2_" + hashlib.sha256(f"{ref}|{start}|{end}|{event.get('type')}".encode()).hexdigest()[:20]
    defaults = {
        "type": "wave_catch", "score": 8, "event_uid": uid, "event_source_ref": ref,
        "perception_evidence_status": "tracker_sidecar", "target_track_id": track,
        "athlete_activity_state": "active",
        "window_refinement": {"status": "unchanged", "first_track_sec": start, "last_track_sec": end,
                              "max_track_gap_sec": 0.2, "max_track_gap_start_sec": start},
    }
    out = dict(event)
    for key, value in defaults.items():
        out.setdefault(key, value)
    return out


def qualify_map(events_by_reel: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """`qualified` applied to every event of an events_by_reel mapping."""
    return {path: [qualified(e) if isinstance(e, dict) else e for e in events] for path, events in events_by_reel.items()}

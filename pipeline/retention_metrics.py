"""Observational editorial metrics for each rendered reel (retention audit of 2026-11-15, PR #385).

Nothing here changes an edit. For every reel the EDL exporter writes, one line is appended to
`<edl dir>/retention_metrics.jsonl` and one line is printed, so what the first second of a reel shows, how
long it takes to reach the athlete, and whether it closes on an action the camera cut can be measured on real
runs before any edit is changed. Thresholds are deliberately absent: the audit asks for them to be calibrated on
real proxies, not assumed.

All inputs already exist: the per-clip EDL record (source window, bound-track samples) and the event the clip
was cut from. A measurement that cannot be made is `null`, never a guess.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = "sportreel.retention_metrics.v1"
FILE_NAME = "retention_metrics.jsonl"
FIRST_WINDOW_SEC = 1.0
# The bound track is thinned in the EDL; a bucket this wide holds at least one sample when the athlete is tracked.
BUCKET_SEC = 0.25


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is not a measurement


def clip_event_facts(event: dict[str, Any], source_path: str | None = None) -> dict[str, Any]:
    """Facts about the event a clip was cut from, read when the clip is recorded. Never raises."""
    facts: dict[str, Any] = {"ends_with_recording": None, "setup_lead_in_sec": None}
    try:
        from pipeline.complete_action_window_policy import ends_with_recording

        facts["ends_with_recording"] = ends_with_recording(event, source_path)
    except Exception:  # noqa: BLE001 - a missing measurement stays null
        pass
    lead = _num(event.get("setup_lead_in_sec"))
    if lead is None:
        setup, action = _num(event.get("setup_start")), _num(event.get("action_start"))
        if setup is not None and action is not None and action >= setup:
            lead = action - setup
    facts["setup_lead_in_sec"] = None if lead is None else round(lead, 3)
    return facts


def first_window_visibility(record: dict[str, Any] | None, window_sec: float = FIRST_WINDOW_SEC) -> dict[str, Any]:
    """How much of a clip's first `window_sec` has the bound athlete tracked, and when the athlete first appears."""
    empty = {"actor_visibility": None, "time_to_tracked_actor_sec": None}
    if not record:
        return empty
    track = record.get("subject_track") or []
    src_fps = _num((record.get("source") or {}).get("fps"))
    start_frame = _num(record.get("src_start_frame"))
    if not track or not src_fps or start_frame is None:
        # No bound track is a fact about the evidence, not proof the athlete is invisible.
        return empty
    offsets = sorted(
        (frame - start_frame) / src_fps
        for frame in (_num(sample.get("src_frame")) for sample in track)
        if frame is not None and frame >= start_frame - 0.5
    )
    if not offsets:
        return empty
    buckets = max(1, int(round(window_sec / BUCKET_SEC)))
    covered = {int(offset // BUCKET_SEC) for offset in offsets if 0 <= offset < window_sec}
    return {
        "actor_visibility": round(len(covered) / buckets, 3),
        "time_to_tracked_actor_sec": round(max(0.0, offsets[0]), 3),
    }


def reel_metrics(edl: dict[str, Any], records: list[dict[str, Any] | None]) -> dict[str, Any]:
    """Metrics of one reel from its EDL and the per-clip records in shot order."""
    fps = _num((edl.get("output") or {}).get("fps")) or 30.0
    shots = edl.get("shots") or []
    durations = [max(0.0, (shot["out_end"] - shot["out_start"]) / fps) for shot in shots]
    known = [record for record in records if record]
    first, last = (known[0] if known else None), (known[-1] if known else None)
    fade_in = next((_num(f.get("sec")) for f in edl.get("fades") or [] if f.get("kind") == "in"), None)
    visibility = first_window_visibility(first)
    lead_in = (first or {}).get("setup_lead_in_sec")
    time_to_actor = visibility["time_to_tracked_actor_sec"]
    return {
        "schema": SCHEMA,
        "output_id": edl.get("output_id"),
        "run_id": edl.get("run_id"),
        "pipeline_commit": edl.get("pipeline_commit"),
        "duration_sec": (edl.get("output") or {}).get("duration_sec"),
        "shot_count": len(shots),
        "first_shot_sec": round(durations[0], 3) if durations else None,
        "longest_shot_sec": round(max(durations), 3) if durations else None,
        "opening_fade_in_sec": fade_in,
        "first_1s_actor_visibility": visibility["actor_visibility"],
        "time_to_tracked_actor_sec": time_to_actor,
        # The cut opens on the catch by design; this is how long the reel runs before the action starts.
        "opening_lead_in_sec": lead_in,
        "time_to_visible_action_sec": (
            None if lead_in is None and time_to_actor is None
            else round(max(lead_in or 0.0, time_to_actor or 0.0), 3)
        ),
        "unresolved_final_action": (last or {}).get("ends_with_recording"),
        "shots_ending_with_recording": sum(1 for record in known if record.get("ends_with_recording") is True),
        "framing_modes": sorted({str(shot.get("mode")) for shot in shots}),
        "event_types": sorted({str(record.get("event_type")) for record in known if record.get("event_type")}),
    }


def write_reel_metrics(edl: dict[str, Any], records: list[dict[str, Any] | None], directory: Path) -> dict[str, Any] | None:
    """Append one reel's metrics to the diagnostics and print them. Never raises."""
    try:
        metrics = reel_metrics(edl, records)
        with (Path(directory) / FILE_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metrics, ensure_ascii=False) + "\n")
        print(
            f"🎬 Retention metrics {metrics['output_id']}: shots={metrics['shot_count']} "
            f"first_shot={metrics['first_shot_sec']}s fade_in={metrics['opening_fade_in_sec']}s "
            f"first_1s_actor_visibility={metrics['first_1s_actor_visibility']} "
            f"time_to_visible_action={metrics['time_to_visible_action_sec']}s "
            f"unresolved_final_action={metrics['unresolved_final_action']}"
        )
        return metrics
    except Exception as exc:  # noqa: BLE001 - observability must never break rendering
        logger.warning("retention metrics failed for %s: %s", edl.get("output_id"), exc)
        return None


def reel_fade_in_sec(default: float = 0.25) -> float:
    """Opening fade of the reel. `SPORTREEL_REEL_FADE_IN_SEC` lets a controlled A/B shorten or remove it;
    unset, the edit is unchanged. Values outside 0–1 s are ignored."""
    raw = os.getenv("SPORTREEL_REEL_FADE_IN_SEC")
    value = _num(raw) if raw not in (None, "") else None
    if value is None or not 0.0 <= value <= 1.0:
        return default
    return value

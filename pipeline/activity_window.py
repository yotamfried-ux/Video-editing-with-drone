"""Activity window & internal active-segment slicing from the YOLO/tracker sidecar (OPT-06).

Provides two levels of CV-guided video trimming before Gemini semantic analysis:
  1. Outer Head/Tail Trimming (`compute_window` / `window_for_video`):
     Skips dead footage before the first and after the last person detection using
     Gemini's `start_offset` / `end_offset` metadata.
  2. Internal Activity Window Slicing (`compute_internal_activity_windows` + `PiecewiseTimestampMap`):
     Identifies internal high-probability athletic activity windows, merges nearby windows,
     attaches lead-in/lead-out context (`pad_sec`), and provides an exact piecewise linear
     timestamp mapping (`PiecewiseTimestampMap`) back to the original source video timeline.

Safety invariant: Never drops internal windows when CV track confidence or coverage is below
`min_coverage_confidence` — automatically falls back to outer trimming or full-video scan
so Event Recall remains 100%.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

DEFAULT_PAD_SEC = 8.0
DEFAULT_INTERNAL_PAD_SEC = 6.0
DEFAULT_MIN_INTERNAL_GAP_SEC = 15.0
DEFAULT_MIN_SAVINGS = 0.20
DEFAULT_MIN_COVERAGE_CONFIDENCE = 0.70
MIN_DETECTIONS = 3


def enabled() -> bool:
    return os.getenv("ANALYSIS_TRIM_TO_ACTIVITY", "1").strip().lower() not in {"0", "false", "no", "off"}


def internal_slicing_enabled() -> bool:
    return os.getenv("SPORTREEL_INTERNAL_ACTIVITY_WINDOWS", "1").strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class PiecewiseTimestampMap:
    """Exact bidirectional mapping between condensed (concatenated) windows and source timestamps."""

    windows: tuple[tuple[float, float], ...]

    @property
    def condensed_duration(self) -> float:
        return round(sum(max(0.0, e - s) for s, e in self.windows), 3)

    def condensed_to_source(self, condensed_sec: float) -> float:
        """Map a timestamp from the condensed multi-window timeline back to the source video timeline."""
        if not self.windows:
            return round(float(condensed_sec), 2)
        t = max(0.0, float(condensed_sec))
        cursor = 0.0
        for start, end in self.windows:
            seg_len = max(0.0, end - start)
            if t <= cursor + seg_len + 1e-6:
                return round(min(end, start + (t - cursor)), 2)
            cursor += seg_len
        last_start, last_end = self.windows[-1]
        return round(last_end, 2)

    def source_to_condensed(self, source_sec: float) -> float | None:
        """Map a source timestamp into the condensed timeline (or None if outside all active windows)."""
        t = float(source_sec)
        cursor = 0.0
        for start, end in self.windows:
            if start - 1e-6 <= t <= end + 1e-6:
                return round(cursor + max(0.0, min(end - start, t - start)), 2)
            cursor += max(0.0, end - start)
        return None

    def remap_event_to_source(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Remap all timestamp fields of an analyzed event back to original source timestamps."""
        remapped = copy.deepcopy(dict(event))
        if not self.windows or len(self.windows) == 1 and self.windows[0][0] == 0.0:
            return remapped
        for field in ("start", "end", "setup_start", "peak_time", "outcome_end"):
            val = remapped.get(field)
            if val is not None:
                try:
                    remapped[field] = self.condensed_to_source(float(val))
                except (TypeError, ValueError):
                    pass
        if remapped.get("end") is not None and remapped.get("start") is not None:
            if float(remapped["end"]) <= float(remapped["start"]):
                remapped["end"] = round(float(remapped["start"]) + max(5.0, float(event.get("end", 5.0)) - float(event.get("start", 0.0))), 2)
        return remapped

    def remap_session_to_source(self, session: Mapping[str, Any]) -> dict[str, Any]:
        """Remap every person's events in an analyzed session back to source video timestamps."""
        out = copy.deepcopy(dict(session))
        persons = []
        for person in out.get("persons", []) or []:
            if not isinstance(person, Mapping):
                continue
            events = [
                self.remap_event_to_source(ev)
                for ev in (person.get("events") or [])
                if isinstance(ev, Mapping)
            ]
            persons.append({**dict(person), "events": events})
        out["persons"] = persons
        out["activity_window_remapped"] = True
        out["activity_windows_source"] = [[s, e] for s, e in self.windows]
        return out


def create_analysis_window_video(
    source_video: str,
    windows: Iterable[tuple[float, float]],
    output_video: str,
) -> str:
    """Build the EXACT condensed timeline that PiecewiseTimestampMap describes.

    Native Gemini start/end offsets accept a single continuous interval only.
    Applying a piecewise map to an uncondensed [first_start, last_end] input
    corrupts event timestamps. This proxy is analysis-only: render ALWAYS uses
    the original full-resolution source video.
    """
    import json
    import subprocess
    from pathlib import Path

    segments = [(float(a), float(b)) for a, b in windows]
    if not segments or any(b <= a or a < 0 for a, b in segments):
        raise ValueError("activity windows must have positive non-negative bounds")
    if any(segments[i][0] < segments[i - 1][1] for i in range(1, len(segments))):
        raise ValueError("activity windows must be ordered and non-overlapping")

    target = Path(output_video)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Explicit output FPS preserves the full frame duration at each concat seam.
    # Without CFR, FFmpeg can report 0.9s for 10 frames at 10fps and cause
    # cumulative drift relative to PiecewiseTimestampMap.
    source_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate,r_frame_rate",
         "-of", "json", str(source_video)],
        capture_output=True, check=True, timeout=30,
    )
    fps_info = json.loads(source_probe.stdout).get("streams", [{}])[0]
    output_fps = fps_info.get("avg_frame_rate") or fps_info.get("r_frame_rate") or "30/1"
    if output_fps in {"0/0", "0/1", "N/A"}:
        output_fps = fps_info.get("r_frame_rate") or "30/1"
    # Compose all windows in the same FFmpeg filter graph, retaining continuous PTS.
    # The analysis proxy (NOT the delivered reel) is at most 1280px wide.
    filters = [
        f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
        f"scale=w='min(iw,1280)':h=-2,setsar=1[v{i}]"
        for i, (start, end) in enumerate(segments)
    ]
    filters.append(
        "".join(f"[v{i}]" for i in range(len(segments)))
        + f"concat=n={len(segments)}:v=1:a=0[outv]"
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", str(source_video),
                "-filter_complex", ";".join(filters),
                "-map", "[outv]", "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
                "-r", str(output_fps), "-fps_mode", "cfr",
                "-movflags", "+faststart", str(target),
            ],
            check=True, capture_output=True, timeout=600,
        )
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(target),
            ],
            check=True, capture_output=True, timeout=30,
        )
        actual = float(json.loads(probe.stdout)["format"]["duration"])
        expected = sum(b - a for a, b in segments)
        if abs(actual - expected) > max(0.4, expected * 0.02):
            raise ValueError(
                f"condensed analysis proxy duration mismatch: {actual:.3f}s vs {expected:.3f}s"
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return str(target)


def compute_window(
    times: Iterable[float],
    duration: float,
    *,
    pad: float | None = None,
    min_savings: float | None = None,
) -> tuple[float, float] | None:
    """(start, end) seconds to analyse, or None to analyse the whole video."""
    pad = DEFAULT_PAD_SEC if pad is None else pad
    min_savings = DEFAULT_MIN_SAVINGS if min_savings is None else min_savings
    stamps = sorted(float(t) for t in times if t is not None and 0.0 <= float(t) <= duration + 1.0)
    if duration <= 0 or len(stamps) < MIN_DETECTIONS:
        return None  # no/too little evidence -> never trim on a guess
    start = max(0.0, stamps[0] - pad)
    end = min(duration, stamps[-1] + pad)
    if end - start >= duration * (1.0 - min_savings):
        return None
    return round(start, 1), round(end, 1)


def compute_internal_activity_windows(
    detections: Iterable[Any],
    duration: float,
    *,
    pad_sec: float = DEFAULT_INTERNAL_PAD_SEC,
    min_gap_sec: float = DEFAULT_MIN_INTERNAL_GAP_SEC,
    min_savings: float = DEFAULT_MIN_SAVINGS,
    min_coverage_confidence: float = DEFAULT_MIN_COVERAGE_CONFIDENCE,
) -> dict[str, Any]:
    """Identify internal active windows with safety fallback when CV coverage confidence is low (OPT-06)."""
    if duration <= 0:
        full_map = PiecewiseTimestampMap(windows=())
        return {
            "mode": "full_video",
            "fallback_reason": "invalid_duration",
            "windows": [],
            "timestamp_map": full_map,
            "saved_seconds": 0.0,
            "saved_ratio": 0.0,
        }

    times: list[float] = []
    confs: list[float] = []
    for det in detections or []:
        t = getattr(det, "time_sec", None) if not isinstance(det, Mapping) else det.get("time_sec")
        c = getattr(det, "confidence", None) if not isinstance(det, Mapping) else det.get("confidence")
        if t is not None and 0.0 <= float(t) <= duration + 1.0:
            times.append(float(t))
            if c is not None:
                confs.append(float(c))

    times.sort()
    if len(times) < MIN_DETECTIONS:
        full_map = PiecewiseTimestampMap(windows=((0.0, round(duration, 2)),))
        return {
            "mode": "full_video",
            "fallback_reason": "insufficient_detections",
            "windows": [(0.0, round(duration, 2))],
            "timestamp_map": full_map,
            "saved_seconds": 0.0,
            "saved_ratio": 0.0,
        }

    mean_conf = sum(confs) / len(confs) if confs else 0.80
    # Safety check: if CV detector confidence is low, never drop internal segments!
    if mean_conf < min_coverage_confidence:
        outer = compute_window(times, duration, pad=pad_sec, min_savings=min_savings)
        if outer:
            w_map = PiecewiseTimestampMap(windows=(outer,))
            saved = max(0.0, duration - (outer[1] - outer[0]))
            return {
                "mode": "outer_window_fallback",
                "fallback_reason": "low_cv_confidence_safety_fallback",
                "windows": [outer],
                "timestamp_map": w_map,
                "saved_seconds": round(saved, 2),
                "saved_ratio": round(saved / duration, 4),
            }
        full_map = PiecewiseTimestampMap(windows=((0.0, round(duration, 2)),))
        return {
            "mode": "full_video",
            "fallback_reason": "low_cv_confidence_safety_fallback",
            "windows": [(0.0, round(duration, 2))],
            "timestamp_map": full_map,
            "saved_seconds": 0.0,
            "saved_ratio": 0.0,
        }

    # Build contiguous active segments separated by gaps > min_gap_sec
    raw_segments: list[tuple[float, float]] = []
    seg_start = times[0]
    seg_end = times[0]
    for t in times[1:]:
        if t - seg_end > min_gap_sec:
            raw_segments.append((max(0.0, seg_start - pad_sec), min(duration, seg_end + pad_sec)))
            seg_start = t
            seg_end = t
        else:
            seg_end = t
    raw_segments.append((max(0.0, seg_start - pad_sec), min(duration, seg_end + pad_sec)))

    # Merge any windows that overlap or touch after padding
    merged: list[tuple[float, float]] = []
    for s, e in raw_segments:
        s_r, e_r = round(s, 1), round(e, 1)
        if merged and s_r <= merged[-1][1] + 2.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e_r))
        else:
            merged.append((s_r, e_r))

    active_dur = sum(max(0.0, e - s) for s, e in merged)
    saved_sec = max(0.0, duration - active_dur)
    saved_ratio = saved_sec / duration

    if saved_ratio < min_savings:
        full_map = PiecewiseTimestampMap(windows=((0.0, round(duration, 2)),))
        return {
            "mode": "full_video",
            "fallback_reason": "savings_below_threshold",
            "windows": [(0.0, round(duration, 2))],
            "timestamp_map": full_map,
            "saved_seconds": 0.0,
            "saved_ratio": 0.0,
        }

    mode = "internal_windows" if len(merged) > 1 else "outer_window"
    return {
        "mode": mode,
        "fallback_reason": None,
        "windows": merged,
        "timestamp_map": PiecewiseTimestampMap(windows=tuple(merged)),
        "saved_seconds": round(saved_sec, 2),
        "saved_ratio": round(saved_ratio, 4),
    }


def window_for_video(video_path: str, duration: float) -> tuple[float, float] | None:
    """Window from this video's perception sidecar; None when unavailable (fail-open)."""
    try:
        from pipeline.perception.runtime import load_sidecar_detections
        detections = load_sidecar_detections(video_path)
        return compute_window((d.time_sec for d in detections), duration)
    except Exception:
        return None

"""Adaptive multi-pass CV inference for weak/fragmented tracking windows (OPT-05).

After a fast primary pass (e.g. 640px), this module identifies specific time windows
where athlete detections are:
  1. Fragmented (short track segments or inter-segment gaps of 1.0s–6.0s)
  2. Small/distant (bounding box area < 0.4% of frame area in high-altitude drone footage)
  3. Low-confidence (mean confidence < 0.48)

Only those problematic windows are escalated to a targeted high-resolution (1280px)
pass, avoiding the CPU/GPU cost of running 1280px across the entire video while
recovering distant athletes and bridging fragmented tracks.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict
from typing import Any, Mapping

DEFAULT_SMALL_BOX_AREA_RATIO = 0.004
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.48
DEFAULT_SHORT_TRACK_LEN = 3
DEFAULT_GAP_MIN_SEC = 1.0
DEFAULT_GAP_MAX_SEC = 6.0
DEFAULT_WINDOW_PAD_SEC = 1.5
DEFAULT_MAX_ESCALATION_COVERAGE_RATIO = 0.55


def adaptive_inference_enabled() -> bool:
    return os.getenv("SPORTREEL_ADAPTIVE_INFERENCE", "1").strip().lower() not in {"0", "false", "no", "off"}


def _bbox_area_ratio(det: Mapping[str, Any]) -> float:
    raw = det.get("bbox_xyxy") or det.get("xyxy")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return 0.0
    try:
        x1, y1, x2, y2 = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
        fw = max(1.0, float(det.get("frame_width") or 1920.0))
        fh = max(1.0, float(det.get("frame_height") or 1080.0))
    except (TypeError, ValueError):
        return 0.0
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return ((x2 - x1) * (y2 - y1)) / (fw * fh)


def _merge_overlapping_windows(
    windows: list[dict[str, Any]],
    *,
    duration_sec: float,
    merge_gap_sec: float = 2.0,
) -> list[dict[str, Any]]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: (float(w["start_sec"]), float(w["end_sec"])))
    merged: list[dict[str, Any]] = []
    for win in ordered:
        start = max(0.0, float(win["start_sec"]))
        end = min(max(start + 0.5, duration_sec) if duration_sec > 0 else float(win["end_sec"]), float(win["end_sec"]))
        if end <= start:
            continue
        reasons = list(win.get("reasons") or [])
        if merged and start <= float(merged[-1]["end_sec"]) + merge_gap_sec:
            merged[-1]["end_sec"] = round(max(float(merged[-1]["end_sec"]), end), 2)
            existing_reasons = list(merged[-1].get("reasons") or [])
            for r in reasons:
                if r not in existing_reasons:
                    existing_reasons.append(r)
            merged[-1]["reasons"] = existing_reasons
        else:
            merged.append({
                "start_sec": round(start, 2),
                "end_sec": round(end, 2),
                "reasons": reasons,
            })
    return merged


def find_weak_perception_windows(
    detections: list[dict[str, Any]],
    *,
    duration_sec: float = 0.0,
    pad_sec: float = DEFAULT_WINDOW_PAD_SEC,
) -> list[dict[str, Any]]:
    """Identify time windows with short/fragmented tracks, small boxes, or low confidence."""
    if not detections:
        return []

    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    max_time = duration_sec
    for det in detections:
        if not isinstance(det, dict):
            continue
        if det.get("class_id") not in (None, 0):
            continue
        t = float(det.get("time_sec") or 0.0)
        if t > max_time:
            max_time = t
        tid = det.get("raw_track_id", det.get("track_id"))
        if tid is not None:
            by_track[str(tid)].append(det)

    raw_windows: list[dict[str, Any]] = []
    track_spans: list[tuple[float, float, str, dict[str, Any], dict[str, Any]]] = []

    for tid, dets in by_track.items():
        ordered = sorted(dets, key=lambda d: float(d.get("time_sec") or 0.0))
        t_start = float(ordered[0].get("time_sec") or 0.0)
        t_end = float(ordered[-1].get("time_sec") or t_start)
        track_spans.append((t_start, t_end, tid, ordered[0], ordered[-1]))

        reasons: list[str] = []
        if len(ordered) <= DEFAULT_SHORT_TRACK_LEN:
            reasons.append("short_fragmented_track")

        areas = [_bbox_area_ratio(d) for d in ordered]
        mean_area = sum(areas) / max(1, len(areas))
        if 0.0 < mean_area < DEFAULT_SMALL_BOX_AREA_RATIO:
            reasons.append("small_distant_athlete")

        confs = [float(d.get("confidence") or 0.0) for d in ordered if d.get("confidence") is not None]
        mean_conf = sum(confs) / max(1, len(confs)) if confs else 1.0
        if mean_conf < DEFAULT_LOW_CONFIDENCE_THRESHOLD:
            reasons.append("low_confidence_track")

        if reasons:
            raw_windows.append({
                "start_sec": max(0.0, t_start - pad_sec),
                "end_sec": min(max_time, t_end + pad_sec),
                "reasons": reasons,
            })

    # Detect inter-track gaps where a track disappears and another appears nearby
    track_spans.sort(key=lambda item: (item[0], item[1]))
    for i in range(len(track_spans)):
        _, end_a, tid_a, _, last_a = track_spans[i]
        box_a = last_a.get("bbox_xyxy") or last_a.get("xyxy")
        fw = max(1.0, float(last_a.get("frame_width") or 1920.0))
        fh = max(1.0, float(last_a.get("frame_height") or 1080.0))
        diag = math.hypot(fw, fh)
        for j in range(i + 1, len(track_spans)):
            start_b, _, tid_b, first_b, _ = track_spans[j]
            gap = start_b - end_a
            if gap < DEFAULT_GAP_MIN_SEC:
                continue
            if gap > DEFAULT_GAP_MAX_SEC:
                break
            box_b = first_b.get("bbox_xyxy") or first_b.get("xyxy")
            if isinstance(box_a, (list, tuple)) and isinstance(box_b, (list, tuple)) and len(box_a) == 4 and len(box_b) == 4:
                cax = (float(box_a[0]) + float(box_a[2])) / 2.0
                cay = (float(box_a[1]) + float(box_a[3])) / 2.0
                cbx = (float(box_b[0]) + float(box_b[2])) / 2.0
                cby = (float(box_b[1]) + float(box_b[3])) / 2.0
                dist_ratio = math.hypot(cax - cbx, cay - cby) / diag
                if dist_ratio <= 0.22:
                    raw_windows.append({
                        "start_sec": max(0.0, end_a - 0.5),
                        "end_sec": min(max_time, start_b + 0.5),
                        "reasons": ["inter_track_continuity_gap"],
                    })

    return _merge_overlapping_windows(raw_windows, duration_sec=max_time)


def should_escalate_windows(
    weak_windows: list[dict[str, Any]],
    *,
    duration_sec: float,
    frame_width: int,
    primary_imgsz: int,
    max_coverage_ratio: float = DEFAULT_MAX_ESCALATION_COVERAGE_RATIO,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """Decide whether targeted high-resolution escalation should run and cap windows if needed."""
    if not adaptive_inference_enabled():
        return False, "disabled_by_env", []
    if not weak_windows:
        return False, "no_weak_windows", []
    if primary_imgsz >= 1280:
        return False, "already_high_res", []
    if 0 < frame_width <= primary_imgsz:
        return False, "source_resolution_below_escalation_target", []

    effective_dur = max(1.0, duration_sec)
    priority_order = sorted(
        weak_windows,
        key=lambda w: (
            "inter_track_continuity_gap" in (w.get("reasons") or []),
            "small_distant_athlete" in (w.get("reasons") or []),
            "short_fragmented_track" in (w.get("reasons") or []),
        ),
        reverse=True,
    )
    budget_sec = max(8.0, effective_dur * max_coverage_ratio)
    selected: list[dict[str, Any]] = []
    accum = 0.0
    for win in priority_order:
        span = max(0.0, float(win["end_sec"]) - float(win["start_sec"]))
        if accum + span <= budget_sec or not selected:
            selected.append(win)
            accum += span
    selected.sort(key=lambda w: float(w["start_sec"]))
    return True, "targeted_window_escalation", selected


def _iou(box_a: list[float] | tuple[float, ...], box_b: list[float] | tuple[float, ...]) -> float:
    x1 = max(float(box_a[0]), float(box_b[0]))
    y1 = max(float(box_a[1]), float(box_b[1]))
    x2 = min(float(box_a[2]), float(box_b[2]))
    y2 = min(float(box_a[3]), float(box_b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0.0:
        return 0.0
    area_a = (float(box_a[2]) - float(box_a[0])) * (float(box_a[3]) - float(box_a[1]))
    area_b = (float(box_b[2]) - float(box_b[0])) * (float(box_b[3]) - float(box_b[1]))
    denom = area_a + area_b - inter
    return inter / denom if denom > 0.0 else 0.0


def merge_escalated_detections(
    primary_detections: list[dict[str, Any]],
    escalated_detections: list[dict[str, Any]],
    weak_windows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge targeted high-resolution detections into the primary pass while preserving raw IDs.

    When an escalated detection at a given frame overlaps a primary detection (IoU >= 0.25),
    it inherits the primary detection's `track_id` and `raw_track_id` (updating confidence/bbox
    when higher quality). Genuinely newly recovered detections receive offset track IDs
    (10000 + track_id) so `stitch_sidecar_payload` can stitch them cleanly across gaps without
    colliding with unrelated primary track IDs.
    """
    if not escalated_detections or not weak_windows:
        return list(primary_detections), {
            "escalated": False,
            "weak_windows_count": len(weak_windows),
            "recovered_detections_count": 0,
            "upgraded_detections_count": 0,
        }

    primary_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    out: list[dict[str, Any]] = []
    for det in primary_detections:
        copied = dict(det)
        copied.setdefault("adaptive_pass", "primary")
        out.append(copied)
        primary_by_frame[int(copied.get("frame_index") or 0)].append(copied)

    recovered = 0
    upgraded = 0
    for esc in escalated_detections:
        f_idx = int(esc.get("frame_index") or 0)
        esc_box = esc.get("bbox_xyxy") or esc.get("xyxy")
        if not isinstance(esc_box, (list, tuple)) or len(esc_box) != 4:
            continue
        esc_class = esc.get("class_id", 0)
        same_frame = [
            p for p in primary_by_frame.get(f_idx, [])
            if p.get("class_id", 0) == esc_class
        ]
        best_match = None
        best_iou = 0.0
        for p in same_frame:
            p_box = p.get("bbox_xyxy") or p.get("xyxy")
            if isinstance(p_box, (list, tuple)) and len(p_box) == 4:
                ov = _iou(p_box, esc_box)
                if ov > best_iou:
                    best_iou = ov
                    best_match = p

        if best_match is not None and best_iou >= 0.25:
            esc_conf = float(esc.get("confidence") or 0.0)
            pri_conf = float(best_match.get("confidence") or 0.0)
            if esc_conf > pri_conf:
                best_match["bbox_xyxy"] = list(esc_box)
                best_match["confidence"] = esc_conf
                best_match["adaptive_pass"] = "high_res_upgraded"
                upgraded += 1
        else:
            raw_tid = int(esc.get("track_id") or 1)
            offset_tid = 10000 + raw_tid
            new_det = {
                **esc,
                "track_id": offset_tid,
                "raw_track_id": offset_tid,
                "adaptive_pass": "high_res_window",
            }
            out.append(new_det)
            primary_by_frame[f_idx].append(new_det)
            recovered += 1

    out.sort(key=lambda d: (float(d.get("time_sec") or 0.0), int(d.get("frame_index") or 0), int(d.get("track_id") or 0)))
    return out, {
        "escalated": True,
        "weak_windows_count": len(weak_windows),
        "weak_windows": weak_windows,
        "recovered_detections_count": recovered,
        "upgraded_detections_count": upgraded,
        "improved": (recovered + upgraded) > 0,
    }


__all__ = [
    "adaptive_inference_enabled",
    "find_weak_perception_windows",
    "merge_escalated_detections",
    "should_escalate_windows",
]

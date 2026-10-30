"""Edit Decision List (EDL) export for rendered reels.

Purpose: make the pipeline's *current* editing behavior measurable and reproducible. The EDL records, per
output shot, which source frames were shown and with which crop / scale / padding, using the exact numbers
that were handed to ffmpeg. It never influences a rendering decision, never reads annotations, and is a no-op
unless ``SPORTREEL_EXPORT_EDL=1``.

Schema ``edl/v1`` (consumed by annotation-studio/server/edl.mjs):

    {schema, output_id, run_id, pipeline_commit, exported_at?, output:{width,height,fps,file,duration_sec},
     mode: contain|tracked_crop|mixed, rotation, mapping: "edl", source / source_sha256 (single-source reels),
     shots:[{out_start, out_end, src_start, speed, mode, source_sha256, source:{width,height}, crop_start,
             crop_end?, keyframes?, track_id, athlete_ref, framing_reason, subject_track?}],
     blends:[{out_start,out_end,kind}], fades:[...], notes:[...]}

Crops are ``{cx, cy, w, h}`` in source pixels of the *displayed* (rotation-applied) frame. ``contain`` is recorded
as the full frame; padding is implied by the uniform-scale transform (the blurred backdrop is cosmetic).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EDL_SCHEMA = "edl/v1"
ENV_FLAG = "SPORTREEL_EXPORT_EDL"
# Overlap used by the editor for a hard cut (kept in sync by test_edl_export_contract against editor._TRANSITION_MAP).
_LOCK = threading.Lock()
_CLIPS: dict[str, dict[str, Any]] = {}
_PROBE_CACHE: dict[str, dict[str, Any]] = {}
_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "").strip().lower() in {"1", "true", "yes"}


def export_dir() -> Path:
    root = Path(os.getenv("TMP_DIR", "/tmp/dtor")) / "pipeline-debug" / "edl"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if math.isfinite(n) else default


# ---------------------------------------------------------------- source facts
def probe_source(path: str) -> dict[str, Any]:
    """Displayed (rotation-applied) dimensions and exact frame rate, via ffprobe. Cached per path."""
    key = os.path.abspath(path)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True, check=True, timeout=60).stdout
    stream = (json.loads(out).get("streams") or [{}])[0]
    num, _, den = str(stream.get("r_frame_rate", "30/1")).partition("/")
    fps_num, fps_den = int(num or 30), int(den or 1) or 1
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(round(-float(side["rotation"]))) % 360
    if "rotate" in (stream.get("tags") or {}):
        rotation = int(round(-float(stream["tags"]["rotate"]))) % 360
    width, height = int(stream["width"]), int(stream["height"])
    if rotation in (90, 270):
        width, height = height, width
    info = {"width": width, "height": height, "rotation": rotation, "fps_num": fps_num, "fps_den": fps_den,
            "fps": fps_num / fps_den}
    _PROBE_CACHE[key] = info
    return info


def source_sha256(path: str) -> str:
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
    if key not in _HASH_CACHE:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        _HASH_CACHE[key] = digest.hexdigest()
    return _HASH_CACHE[key]


# ---------------------------------------------------------------- crop geometry
def _even(value: float, minimum: int = 2) -> int:
    result = max(minimum, int(round(value)))
    return result if result % 2 == 0 else result - 1


def follow_value(points: list[tuple[float, float]], t: float) -> float:
    """Exactly what ``framing.follow_expression`` evaluates inside ffmpeg (incl. extrapolation before the first point)."""
    value = points[-1][1]
    for (t0, v0), (t1, v1) in reversed(list(zip(points, points[1:]))):
        if t < t1:
            value = v0 + (v1 - v0) * (t - t0) / max(t1 - t0, 1e-3)
    return value


def clip_geometry(
    decision: Any,
    event: dict[str, Any],
    source: dict[str, Any],
    out_w: int,
    out_h: int,
    start: float,
    duration: float,
    out_fps: float,
) -> dict[str, Any]:
    """Crop geometry for one clip, mirroring ``quality_preserving_framing._render_clip`` branch by branch."""
    width, height = float(source["width"]), float(source["height"])
    mode = decision.mode
    notes: list[str] = []
    perc_w = _num(event.get("perception_frame_width") or event.get("frame_width"))
    perc_h = _num(event.get("perception_frame_height") or event.get("frame_height"))
    if perc_w and perc_h and (abs(perc_w - width) > 1 or abs(perc_h - height) > 1):
        notes.append("perception_dims_differ_from_source")

    if mode == "contain":
        crop = {"cx": width / 2, "cy": height / 2, "w": width, "h": height}
        return {"mode": "contain", "crop_start": crop, "notes": notes}

    if mode == "follow_crop" and decision.path:
        frame_w, frame_h = decision.frame_width, decision.frame_height
        from pipeline.quality_preserving_framing import _base_crop_ratios

        base_w_ratio, base_h_ratio = _base_crop_ratios(frame_w, frame_h)
        crop_w = _even(base_w_ratio * frame_w / decision.zoom)
        crop_h = _even(base_h_ratio * frame_h / decision.zoom)
        pts_x = [(round(p[0] - start, 3), p[1]) for p in decision.path]
        pts_y = [(round(p[0] - start, 3), p[2]) for p in decision.path]
        total = max(1, int(round(duration * out_fps)))
        frames = {0, total - 1}
        for t, _ in pts_x:
            f = int(round(t * out_fps))
            if 0 <= f < total:
                frames.add(f)
        keyframes = []
        for f in sorted(frames):
            t = f / out_fps
            left, top = follow_value(pts_x, t), follow_value(pts_y, t)
            keyframes.append({"out_frame": f, "crop": {"cx": left + crop_w / 2, "cy": top + crop_h / 2, "w": crop_w, "h": crop_h}})
        return {"mode": "tracked_crop", "crop_start": keyframes[0]["crop"], "keyframes": keyframes,
                "follow": True, "notes": notes}

    # fixed crop branch (decision.mode == "tracked_crop")
    base_w = height * 9.0 / 16.0
    base_h = height
    if base_w > width:
        base_w, base_h = width, width * 16.0 / 9.0
    crop_w, crop_h = _even(base_w / decision.zoom), _even(base_h / decision.zoom)
    cx_px, cy_px = decision.crop_x * width, decision.crop_y * height
    x = max(0, min(_even(width - crop_w, 0), int(round(cx_px - crop_w / 2))))
    y = max(0, min(_even(height - crop_h, 0), int(round(cy_px - crop_h / 2))))
    return {"mode": "tracked_crop",
            "crop_start": {"cx": x + crop_w / 2, "cy": y + crop_h / 2, "w": crop_w, "h": crop_h}, "notes": notes}


# ---------------------------------------------------------------- tracking evidence
SUBJECT_TRACK_MIN_FRAME_STRIDE = 5


def _subject_track(source_path: str, event: dict[str, Any], src_fps: float, start: float, end: float) -> list[dict[str, Any]]:
    """Bound track samples (normalized boxes at source frames), thinned to one per few frames. Existing evidence only."""
    if event.get("track_id") is None:
        return []
    try:
        from pipeline.quality_preserving_framing import _track_trajectory

        samples = _track_trajectory(source_path, {**event, "start": start, "end": end})
    except Exception as exc:  # noqa: BLE001
        logger.warning("subject track unavailable for %s: %s", source_path, exc)
        return []
    out: list[dict[str, Any]] = []
    last = -10**9
    for sample in sorted(samples, key=lambda item: item["time_sec"]):
        frame = int(round(sample["time_sec"] * src_fps))
        if frame - last < SUBJECT_TRACK_MIN_FRAME_STRIDE:
            continue
        last = frame
        out.append({"src_frame": frame,
                    "bbox": {"x": round(sample["x1"], 5), "y": round(sample["y1"], 5),
                             "w": round(sample["x2"] - sample["x1"], 5), "h": round(sample["y2"] - sample["y1"], 5)},
                    "confidence": round(sample["confidence"], 3)})
    return out


# ---------------------------------------------------------------- per-clip registry
def record_clip(
    clip_path: str,
    source_path: str,
    event: dict[str, Any],
    decision: Any,
    start: float,
    end: float,
    out_w: int,
    out_h: int,
    out_fps: float,
) -> None:
    """Remember how one clip was made. Never raises: export failures must not affect rendering."""
    if not enabled():
        return
    try:
        source = probe_source(source_path)
        duration = max(0.0, end - start)
        geom = clip_geometry(decision, event, source, out_w, out_h, start, duration, out_fps)
        src_fps = source["fps"]
        record = {
            "clip": os.path.abspath(clip_path),
            "source_path": os.path.abspath(source_path),
            "source_file": os.path.basename(source_path),
            "source_sha256": source_sha256(source_path),
            "source": {"width": source["width"], "height": source["height"], "fps": src_fps, "rotation": source["rotation"]},
            "event_id": event.get("event_id") or event.get("id"),
            "event_type": event.get("type"),
            "src_start_sec": start, "src_end_sec": end,
            "src_start_frame": int(math.ceil(start * src_fps - 1e-6)),
            "speed": src_fps / out_fps,
            "track_id": None if event.get("track_id") is None else str(event.get("track_id")),
            "athlete_ref": event.get("athlete_id") or event.get("athlete_label") or event.get("person_id"),
            "framing_reason": getattr(decision, "reason", None),
            "framing_confidence": getattr(decision, "confidence", None),
            "subject_track": _subject_track(source_path, event, src_fps, start, end),
            **geom,
        }
        with _LOCK:
            _CLIPS[os.path.abspath(clip_path)] = record
            with (export_dir() / "edl_clips.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - observability must never break production rendering
        logger.warning("EDL clip record failed for %s: %s", clip_path, exc)


# ---------------------------------------------------------------- reel assembly
def rendered_offsets(durations: list[float], overlaps: list[float]) -> list[float]:
    """Clip start offsets (sec) using the editor's xfade cursor rule (same as editor._events_with_rendered_timeline)."""
    cursor, starts = 0.0, []
    for index, duration in enumerate(durations):
        start = round(cursor, 3)
        starts.append(start)
        end = round(start + max(0.0, duration), 3)
        overlap = overlaps[index] if index < len(overlaps) else 0.0
        cursor = max(start, end - overlap)
    return starts


def build_reel_edl(
    clip_paths: list[str],
    output_path: str,
    durations: list[float],
    overlaps: list[tuple[str, float]],
    fps: float,
    out_w: int,
    out_h: int,
    run_id: str | None,
    commit: str | None,
    fades: tuple[float, float] = (0.25, 0.40),
) -> dict[str, Any]:
    notes: list[str] = []
    records = []
    for path in clip_paths:
        rec = _CLIPS.get(os.path.abspath(path))
        if rec is None:
            notes.append(f"clip_not_recorded:{os.path.basename(path)}")
        records.append(rec)
    starts = rendered_offsets(durations, [o[1] for o in overlaps])
    shots, blends = [], []
    for i, (rec, start, dur) in enumerate(zip(records, starts, durations)):
        out_start = int(round(start * fps))
        out_end = out_start + int(round(dur * fps))
        if rec is None:
            continue
        shot: dict[str, Any] = {
            "out_start": out_start, "out_end": out_end, "src_start": rec["src_start_frame"], "speed": rec["speed"],
            "mode": rec["mode"], "source_sha256": rec["source_sha256"], "source": rec["source"],
            "crop_start": rec["crop_start"], "event_id": rec["event_id"], "track_id": rec["track_id"],
            "athlete_ref": rec["athlete_ref"], "framing_reason": rec["framing_reason"],
            "source_file": rec["source_file"],
        }
        if rec.get("subject_track"):
            shot["subject_track"] = rec["subject_track"]
        if rec.get("keyframes"):
            shot["keyframes"] = [{"out_frame": out_start + k["out_frame"], "crop": k["crop"]} for k in rec["keyframes"]]
        if rec.get("notes"):
            shot["notes"] = rec["notes"]
        shots.append(shot)
        if i < len(overlaps):
            ov = int(round(overlaps[i][1] * fps))
            if ov > 0:
                blends.append({"out_start": out_end - ov, "out_end": out_end, "kind": overlaps[i][0]})
    # A shot ends where the next begins; the cross-dissolve frames are listed as blends and are not scored.
    for a, b in zip(shots, shots[1:]):
        if a["out_end"] > b["out_start"]:
            a["out_end"] = b["out_start"]
            if a.get("keyframes"):
                a["keyframes"] = [k for k in a["keyframes"] if k["out_frame"] < a["out_end"]]
    modes = {s["mode"] for s in shots}
    sources = {s["source_sha256"]: s["source"] for s in shots}
    edl: dict[str, Any] = {
        "schema": EDL_SCHEMA,
        "output_id": Path(output_path).stem,
        "run_id": run_id or "unknown",
        "pipeline_commit": commit or "unknown",
        "mapping": "edl",
        "output": {"width": out_w, "height": out_h, "fps": fps, "file": os.path.basename(output_path),
                   "duration_sec": round(max((s["out_end"] for s in shots), default=0) / fps, 3)},
        "mode": next(iter(modes)) if len(modes) == 1 else "mixed",
        "rotation": 0,
        "shots": shots, "blends": blends,
        "fades": [{"kind": "in", "sec": fades[0]}, {"kind": "out", "sec": fades[1]}],
        "overlay": ["logo_watermark"],
        "sources": sources, "notes": notes,
    }
    if len(sources) == 1:
        sha, dims = next(iter(sources.items()))
        edl["source_sha256"], edl["source"] = sha, {"width": dims["width"], "height": dims["height"]}
    else:
        # multi-source reel: top-level fields intentionally absent; every shot carries its own source.
        edl["source_sha256"] = "multiple"
        edl["source"] = {"width": 0, "height": 0}
    return edl


def write_reel_edl(
    clip_paths: list[str],
    output_path: str,
    transitions: list[str] | None,
    fps: float,
    out_w: int,
    out_h: int,
) -> str | None:
    """Assemble and write the EDL beside the diagnostics. Never raises."""
    if not enabled() or not output_path:
        return None
    try:
        from pipeline.stages import editor

        durations = [float(editor._get_duration(p)) for p in clip_paths]
        overlaps = editor._pair_transitions(len(clip_paths), transitions)
        edl = build_reel_edl(
            clip_paths, output_path, durations, overlaps, fps, out_w, out_h,
            run_id=os.getenv("PIPELINE_RUN_ID"), commit=os.getenv("GITHUB_SHA") or os.getenv("SPORTREEL_COMMIT"))
        target = export_dir() / f"{edl['output_id']}.edl.json"
        target.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("EDL write failed for %s: %s", output_path, exc)
        return None


def reset_for_tests() -> None:
    _CLIPS.clear()
    _PROBE_CACHE.clear()
    _HASH_CACHE.clear()

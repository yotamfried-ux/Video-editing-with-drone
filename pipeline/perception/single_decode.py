"""Decode each 4K source ONCE for perception and the Gemini analysis proxy.

Before this module, every new source was fully decoded at 4K at least three times:
  1. the primary YOLO pass (Ultralytics ``vid_stride`` still decodes every frame),
  2. the high-res escalation / zero-detection rescue pass, which additionally seeked the 4K
     long-GOP stream once PER SAMPLED FRAME (each seek re-decodes from the previous keyframe:
     measured ~1.2-1.7 s per frame on a 4-vCPU runner), and
  3. the 720p Gemini proxy encode in ``pipeline.stages.analyzer._make_proxy``.

Run 42474968394 spent 18,290 s in ``yolo_perception`` (8 sources hit the 1200 s timeout) for clips of
well under a minute. Locally, a 20 s 4K60 clip took 770 s, 722 s of it in the seek-per-frame escalation.

Now one ffmpeg process decodes the source once and writes, from that single decode:
  * a near-lossless (x264 CRF 4, 4:4:4, ~51 dB PSNR vs lossless) intermediate at the escalation resolution (1280 px wide) with the
    exact same frame count and order (``-fps_mode passthrough``), which both YOLO passes read, and
  * the Gemini proxy with byte-for-byte the same filter/encoder settings ``_make_proxy`` uses.

Why this does not reduce perception quality: the primary pass letterboxes to 640 px and the escalation
pass to 1280 px, so the detector never saw more than 1280 px of width even when it was handed the 4K
frame. The intermediate keeps that resolution and is downscaled with
an area (box) filter, which aliases less than the INTER_LINEAR resize the detector applied to 4K frames.
The intermediate is near-lossless (51 dB PSNR vs lossless), keeps full chroma (4:4:4) and is deleted when
perception finishes; only one exists at a time (see runtime._producer_slots).
Boxes are mapped back to source pixels so sidecars keep the source frame dimensions.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Gemini proxy contract. pipeline.stages.analyzer._make_proxy imports these, so the pre-made proxy and a
# proxy encoded by the analyzer itself are produced by identical settings.
PROXY_MAX_WIDTH = 1280
PROXY_SCALE_FILTER = f"scale={PROXY_MAX_WIDTH}:-2"
PROXY_ENCODE_ARGS = ["-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-an"]

# Perception intermediate: the escalation pass runs at imgsz=1280, so 1280 px wide is the highest
# resolution any YOLO pass consumes.
INTERMEDIATE_WIDTH = 1280
# Near-lossless, full chroma (4:4:4). Measured on worst-case noisy 4K60: CRF 4 is 51 dB PSNR against a true
# lossless (-qp 0) intermediate at ~60% of its size (lossless was 5.4x the source bytes); detections on identical
# frames matched the old 4K path as closely as lossless did (scripts/ab_perception_decode.py).
_INTERMEDIATE_ENCODE_ARGS = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "4", "-pix_fmt", "yuv444p", "-an"]
# Worst case the intermediate is ~3.5x the source bytes; keep a margin for downloads, proxies and renders.
_DISK_FACTOR = 4.0
_DISK_RESERVE_BYTES = 3 * 1024 ** 3
_MARKER_SUFFIX = ".premade.json"

# QA source-evidence copy. pipeline.source_evidence cuts its <=1280 px, CRF 26 windows from the 4K source; while
# rendering, that re-decoded the same 4K windows for every reel (run 42814819534: ~14 s per window, competing with
# the renderer for the CPU). The single decode also writes a near-transparent 1280 px copy (CRF 18, native frame
# rate, same bicubic scale as the evidence clips) that QA cuts from instead. One more decode avoided per window.
EVIDENCE_SCALE_FILTER = "scale=1280:-2"
_EVIDENCE_ENCODE_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an"]
_EVIDENCE_ENV = "SPORTREEL_EVIDENCE_PROXY"
_DISABLE_ENV = "SPORTREEL_SINGLE_DECODE"


def single_decode_enabled() -> bool:
    return os.getenv(_DISABLE_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _tmp_dir() -> str:
    return os.getenv("TMP_DIR", "/tmp/dtor")


def proxy_path_for(video_path: str) -> str:
    """Where the Gemini proxy for ``video_path`` lives (same naming as the analyzer always used)."""
    return os.path.join(_tmp_dir(), f"proxy_{Path(video_path).stem}.mp4")


def _source_fingerprint(video_path: str) -> dict[str, Any]:
    st = os.stat(video_path)
    return {
        "source": os.path.abspath(video_path),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "scale": PROXY_SCALE_FILTER,
        "encode": PROXY_ENCODE_ARGS,
    }


def evidence_path_for(video_path: str) -> str:
    return os.path.join(_tmp_dir(), f"qa_evidence_{Path(video_path).stem}.mp4")


def _evidence_fingerprint(video_path: str) -> dict[str, Any]:
    return {**_source_fingerprint(video_path), "scale": EVIDENCE_SCALE_FILTER, "encode": _EVIDENCE_ENCODE_ARGS}


def evidence_enabled() -> bool:
    return os.getenv(_EVIDENCE_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def evidence_copy_for(video_path: str) -> str | None:
    """The 1280 px evidence copy made by the single decode for exactly this source file, else None."""
    path = evidence_path_for(video_path)
    try:
        if not (os.path.exists(path) and os.path.getsize(path) > 0):
            return None
        with open(path + _MARKER_SUFFIX, encoding="utf-8") as handle:
            if json.load(handle) != _evidence_fingerprint(video_path):
                return None
        return path
    except (OSError, ValueError):
        return None


def claim_premade_proxy(video_path: str) -> str | None:
    """Return a proxy pre-made by the perception single-decode pass for exactly this source, else None.

    The marker binds the proxy to the source file (path, size, mtime) and to the proxy settings, so a stale
    or foreign file is never uploaded to Gemini. The marker is consumed; the caller owns the proxy file.
    """
    proxy = proxy_path_for(video_path)
    marker = proxy + _MARKER_SUFFIX
    try:
        if not (os.path.exists(proxy) and os.path.getsize(proxy) > 0 and os.path.exists(marker)):
            return None
        with open(marker, encoding="utf-8") as handle:
            recorded = json.load(handle)
        if recorded != _source_fingerprint(video_path):
            return None
        return proxy
    except (OSError, ValueError):
        return None
    finally:
        try:
            if os.path.exists(marker):
                os.remove(marker)
        except OSError:
            pass


def discard_premade_proxy(video_path: str) -> None:
    """Delete an unused pre-made proxy (e.g. when the Gemini analysis was served from cache)."""
    proxy = proxy_path_for(video_path)
    for path in (proxy + _MARKER_SUFFIX, proxy):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _probe(video_path: str) -> dict[str, Any] | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,nb_frames", "-of", "json", video_path],
            capture_output=True, text=True, timeout=60, check=True,
        )
        stream = (json.loads(out.stdout).get("streams") or [{}])[0]
        return {
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "nb_frames": int(stream["nb_frames"]) if str(stream.get("nb_frames") or "").isdigit() else None,
        }
    except Exception:
        return None


def _decoded_frame_count(path: str) -> int | None:
    """Frame count as the detector's reader (OpenCV) reports it; container nb_frames when OpenCV is absent."""
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(path)
        try:
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        finally:
            cap.release()
        if count > 0:
            return count
    except Exception:
        pass
    return (_probe(path) or {}).get("nb_frames")


def prepare_single_decode(video_path: str, work_dir: str, *, write_proxy: bool = True, timeout: int = 900) -> dict[str, Any]:
    """Decode ``video_path`` once; return the frame source YOLO should read and the box scale back to source.

    Returns ``{"frames_path", "scale_x", "scale_y", "source_width", "source_height", "mode", ...}``. On any
    problem it returns ``mode="direct"`` with ``frames_path=video_path`` (the previous behaviour), so this
    optimisation can never block perception.
    """
    direct = {"frames_path": video_path, "scale_x": 1.0, "scale_y": 1.0, "mode": "direct", "intermediate": None}
    if not single_decode_enabled() or shutil.which("ffmpeg") is None:
        return {**direct, "reason": "disabled_or_ffmpeg_missing"}
    info = _probe(video_path)
    if not info or info["width"] <= 0 or info["height"] <= 0:
        return {**direct, "reason": "probe_failed"}
    src_w, src_h = info["width"], info["height"]
    if src_w <= INTERMEDIATE_WIDTH:
        return {**direct, "source_width": src_w, "source_height": src_h, "reason": "source_not_larger_than_intermediate"}

    os.makedirs(work_dir, exist_ok=True)
    try:
        need = int(os.path.getsize(video_path) * _DISK_FACTOR) + _DISK_RESERVE_BYTES
        free = shutil.disk_usage(work_dir).free
    except OSError:
        need, free = 0, 0
    if free < need:
        return {**direct, "source_width": src_w, "source_height": src_h,
                "reason": f"insufficient_disk free={free} need={need}"}
    # MP4 stores an exact frame count (MKV only lets OpenCV estimate it), which the exactness check needs.
    intermediate = os.path.join(work_dir, f"perception_{Path(video_path).stem}_{os.getpid()}.mp4")
    proxy = proxy_path_for(video_path) if write_proxy else None
    evidence = evidence_path_for(video_path) if evidence_enabled() else None
    for path in (proxy, evidence):
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    branches = [("perc", f"scale={INTERMEDIATE_WIDTH}:-2:flags=area,format=yuv444p")]
    if proxy:
        branches.append(("prox", PROXY_SCALE_FILTER))
    if evidence:
        branches.append(("evid", EVIDENCE_SCALE_FILTER))
    if len(branches) == 1:
        graph = f"[0:v]{branches[0][1]}[{branches[0][0]}]"
    else:
        graph = f"[0:v]split={len(branches)}" + "".join(f"[{name}_in]" for name, _ in branches) + ";" + ";".join(
            f"[{name}_in]{flt}[{name}]" for name, flt in branches
        )
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_path, "-filter_complex", graph,
           "-map", "[perc]", "-fps_mode", "passthrough", *_INTERMEDIATE_ENCODE_ARGS, intermediate]
    if proxy:
        cmd += ["-map", "[prox]", *PROXY_ENCODE_ARGS, proxy]
    if evidence:
        cmd += ["-map", "[evid]", *_EVIDENCE_ENCODE_ARGS, evidence]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    except Exception as exc:  # noqa: BLE001 - fall back to the direct (slower) path, never fail perception here
        for path in (intermediate, proxy, evidence):
            if path and os.path.exists(path):
                os.remove(path)
        detail = getattr(exc, "stderr", "") or str(exc)
        return {**direct, "source_width": src_w, "source_height": src_h, "reason": f"ffmpeg_failed: {str(detail)[-300:]}"}

    # Frame-exactness: perception frame indices / time_sec must stay identical to reading the source.
    src_frames = _decoded_frame_count(video_path) or info.get("nb_frames")
    int_frames = _decoded_frame_count(intermediate)
    int_info = _probe(intermediate) or {}
    if not src_frames or not int_frames or src_frames != int_frames or not int_info.get("width"):
        os.remove(intermediate)
        for path in (proxy, evidence):
            if path and os.path.exists(path):
                os.remove(path)
        return {**direct, "source_width": src_w, "source_height": src_h,
                "reason": f"frame_count_mismatch source={src_frames} intermediate={int_frames}"}

    if proxy:
        with open(proxy + _MARKER_SUFFIX, "w", encoding="utf-8") as handle:
            json.dump(_source_fingerprint(video_path), handle)
    if evidence and os.path.exists(evidence):
        with open(evidence + _MARKER_SUFFIX, "w", encoding="utf-8") as handle:
            json.dump(_evidence_fingerprint(video_path), handle)
    return {
        "frames_path": intermediate,
        "intermediate": intermediate,
        "proxy": proxy,
        "evidence": evidence,
        "mode": "single_decode",
        "source_width": src_w,
        "source_height": src_h,
        "intermediate_width": int(int_info["width"]),
        "intermediate_height": int(int_info["height"]),
        "scale_x": src_w / float(int_info["width"]),
        "scale_y": src_h / float(int_info["height"]),
        "frame_count": int_frames,
    }


def to_source_coordinates(detections: list[dict[str, Any]], decode: dict[str, Any]) -> list[dict[str, Any]]:
    """Map boxes measured on the intermediate back to source pixels; keep source frame dimensions."""
    if decode.get("mode") != "single_decode":
        return detections
    sx, sy = float(decode["scale_x"]), float(decode["scale_y"])
    src_w, src_h = int(decode["source_width"]), int(decode["source_height"])
    out = []
    for det in detections:
        box = det.get("bbox_xyxy")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            det = {**det, "bbox_xyxy": [float(box[0]) * sx, float(box[1]) * sy, float(box[2]) * sx, float(box[3]) * sy]}
        out.append({**det, "frame_width": src_w, "frame_height": src_h})
    return out


def cleanup(decode: dict[str, Any]) -> None:
    path = decode.get("intermediate")
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


__all__ = [
    "INTERMEDIATE_WIDTH",
    "PROXY_ENCODE_ARGS",
    "PROXY_MAX_WIDTH",
    "PROXY_SCALE_FILTER",
    "claim_premade_proxy",
    "cleanup",
    "discard_premade_proxy",
    "prepare_single_decode",
    "proxy_path_for",
    "single_decode_enabled",
    "to_source_coordinates",
]

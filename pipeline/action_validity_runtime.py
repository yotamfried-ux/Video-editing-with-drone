"""Production wiring of observed action validity (FIX-PQ-14-002, cycle 14b).

Called from publishable_reel_policy._qualification_inputs - the one place where every FINAL shot of a reel (final
window after all boundary policies, bound target track, source file) is turned into qualification evidence - and
only while SPORTREEL_ACTION_VALIDITY is enabled (no model call, no cost otherwise).

Per shot:
  1. sample the COMPLETE action window: pass A and pass B each cover [start, end] end to end (both edges included,
     pass B offset by half a step), so take-off, continuation and ending are always seen. The step adapts to the
     window (<= MAX_SAMPLES_PER_PASS crops, never sparser than MAX_STEP_SEC unless the window is very long, in which
     case the spacing is recorded and the coverage check below applies);
  2. validate the target before any model call: each sample takes the detection of the bound track (stitched
     backwards through the same actor's earlier tracklets) nearest in time; the target must be present in >=
     MIN_PRESENT_RATIO of the samples AND in the first and last ACTION_EDGE_FRACTION of the window. Otherwise the shot
     is UNCERTAIN ("target_coverage_insufficient") - an unverifiable shot never becomes VALID and no money is spent;
  3. crop each sample from the real video at the target box, label it with its clip time, tile a grid per pass;
  4. ask the model (budget-checked, labelled for cost accounting) for per-frame observations; the answer must cover
     exactly the requested times (action_validity.parse_observations); the deterministic decision follows.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import tempfile
from typing import Any, Callable

try:
    from pipeline import action_validity as av
except ModuleNotFoundError:          # loaded by file path (publishable_reel_policy._load_sibling) without the package
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline import action_validity as av

logger = logging.getLogger(__name__)

MAX_SAMPLES_PER_PASS = 16
MIN_SAMPLES_PER_PASS = 8
MAX_STEP_SEC = 1.0
MIN_PRESENT_RATIO = 0.75
ACTION_EDGE_FRACTION = 0.2
TILE = 256
MODEL = "gemini-2.5-flash"


# ------------------------------------------------------------------ sampling

def sample_plan(start: float, end: float) -> dict[str, Any]:
    """Two interleaved passes, each spanning the whole window including both edges."""
    dur = max(0.0, float(end) - float(start))
    n = int(min(MAX_SAMPLES_PER_PASS, max(MIN_SAMPLES_PER_PASS, math.ceil(dur / MAX_STEP_SEC) + 1)))
    step = dur / (n - 1) if n > 1 else 0.0
    a = [round(start + i * step, 2) for i in range(n)]
    b = [round(start, 2)] + [round(start + (i + 0.5) * step, 2) for i in range(n - 1)] + [round(end, 2)]
    b = sorted(set(b))
    return {"passes": [a, b], "step_sec": round(step, 3), "window": [round(start, 2), round(end, 2)]}


def coverage_of(times: list[float], start: float, end: float) -> dict[str, Any]:
    t = sorted(times)
    gaps = [y - x for x, y in zip(t, t[1:])]
    return {"first": t[0] if t else None, "last": t[-1] if t else None,
            "covers_start": bool(t) and abs(t[0] - start) <= 0.06, "covers_end": bool(t) and abs(t[-1] - end) <= 0.06,
            "max_gap_sec": round(max(gaps), 3) if gaps else None}


# ------------------------------------------------------------------ target identity

def _f(det: Any, name: str) -> Any:
    return det.get(name) if isinstance(det, dict) else getattr(det, name, None)


def target_samples(detections: list[Any], track_id: Any, times: list[float], tol: float) -> list[Any | None]:
    from pipeline.action_onset import stitched_actor_detections
    actor = stitched_actor_detections(detections, track_id)
    out = []
    for t in times:
        near = [d for d in actor if abs(float(_f(d, "time_sec")) - t) <= tol]
        out.append(min(near, key=lambda d: abs(float(_f(d, "time_sec")) - t)) if near else None)
    return out


def identity_check(samples: list[Any | None], times: list[float], start: float, end: float) -> dict[str, Any]:
    present = [s is not None for s in samples]
    ratio = sum(present) / len(present) if present else 0.0
    edge = ACTION_EDGE_FRACTION * max(end - start, 0.0)
    head = any(p for p, t in zip(present, times) if t <= start + edge)
    tail = any(p for p, t in zip(present, times) if t >= end - edge)
    tracks = sorted({str(_f(s, "tracker_id") if _f(s, "tracker_id") is not None else _f(s, "track_id"))
                     for s in samples if s is not None})
    return {"present_ratio": round(ratio, 3), "present_at_start": head, "present_at_end": tail,
            "present_at_takeoff": head, "present_at_ending": tail,
            "track_ids": tracks, "ok": ratio >= MIN_PRESENT_RATIO and head and tail}


# ------------------------------------------------------------------ media

def _crop_frame(video_path: str, det: Any, out_path: str) -> bool:
    from pipeline import runtime_quality as rq
    x, y, w, h = rq._crop_box(det)
    vf = (f"crop=iw*{w:.5f}:ih*{h:.5f}:iw*{x:.5f}:ih*{y:.5f},scale={TILE}:{TILE}:force_original_aspect_ratio=decrease,"
          f"pad={TILE}:{TILE}:(ow-iw)/2:(oh-ih)/2")
    t = max(0.0, float(_f(det, "time_sec")))
    # A sample at the very end of the recording (windows that run to the last frame, EXP-14-002 dry run: 0130 at
    # 8.63 s) seeks past the last decodable frame and ffmpeg writes nothing; step back a few frames before giving up.
    for back in (0.0, 0.05, 0.15, 0.35):
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{max(0.0, t - back):.3f}",
               "-i", video_path, "-frames:v", "1", "-vf", vf, "-q:v", "3", out_path]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        except Exception as exc:
            logger.debug("action-validity crop failed at %.3f: %s", t - back, exc)
            continue
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return True
    return False


def build_grid(video_path: str, samples: list[Any], times: list[float]) -> bytes | None:
    """Labelled grid of target crops, in time order; None when any crop fails (a partial grid is no evidence)."""
    from PIL import Image, ImageDraw
    cols = 4
    rows = math.ceil(len(samples) / cols)
    with tempfile.TemporaryDirectory(prefix="avgrid-") as tmp:
        tiles = []
        for i, det in enumerate(samples):
            path = os.path.join(tmp, f"{i}.jpg")
            if not _crop_frame(video_path, det, path):
                return None
            tiles.append(path)
        sheet = Image.new("RGB", (cols * TILE, rows * TILE), (16, 16, 16))
        draw = ImageDraw.Draw(sheet)
        for i, (path, t) in enumerate(zip(tiles, times)):
            with Image.open(path) as im:
                sheet.paste(im.convert("RGB").resize((TILE, TILE)), ((i % cols) * TILE, (i // cols) * TILE))
            x, y = (i % cols) * TILE + 4, (i // cols) * TILE + 4
            draw.rectangle([x - 2, y - 2, x + 62, y + 16], fill=(0, 0, 0))
            draw.text((x, y), f"{t:.1f}s", fill=(255, 255, 0))
        out = os.path.join(tmp, "grid.jpg")
        sheet.save(out, "JPEG", quality=88)
        with open(out, "rb") as fh:
            return fh.read()


# ------------------------------------------------------------------ model

def default_ask(image: bytes, prompt: str) -> str:
    """Gemini through integrations.gemini (the same wrapper as every production call): it enforces the run's LLM
    budget (qualification.check_llm_budget; this label is a DOWNSTREAM phase, so it may use the reserve) and records
    tokens and cost under the caller label `action_validity_runtime.default_ask`. Inline image, no Files API upload."""
    from google.genai import types
    from integrations.gemini import genai
    model = genai.GenerativeModel(model_name=MODEL)
    response = model.generate_content([types.Part.from_bytes(data=image, mime_type="image/jpeg"), prompt],
                                      request_options={"timeout": 60})
    return (getattr(response, "text", "") or "").strip()


# ------------------------------------------------------------------ per shot

def _window(event: dict[str, Any]) -> tuple[float, float] | None:
    for a, b in (("final_cut_start", "final_cut_end"), ("start", "end")):
        try:
            s, e = float(event.get(a)), float(event.get(b))
        except (TypeError, ValueError):
            continue
        if e > s:
            return s, e
    return None


def observe_event(event: dict[str, Any], video_path: str, detections: list[Any],
                  ask: Callable[[bytes, str], str] | None = None) -> dict[str, Any]:
    from pipeline.sport_profiles import profile_for_event
    policy = profile_for_event(event).action_validity
    if not policy.established_states:
        return {"prompt_version": av.PROMPT_VERSION, "verdict": av.VALID, "basis": "profile_has_no_validity_policy"}
    window = _window(event)
    track = event.get("target_track_id")
    if window is None or track in (None, "") or not video_path or not os.path.exists(video_path):
        return {"prompt_version": av.PROMPT_VERSION, "verdict": av.UNCERTAIN, "basis": "no_window_track_or_media"}
    start, end = window
    plan = sample_plan(start, end)
    tol = max(0.3, plan["step_sec"] / 2)
    checks, grids = [], []
    for times in plan["passes"]:
        samples = target_samples(detections, track, times, tol)
        ident = identity_check(samples, times, start, end)
        cov = coverage_of(times, start, end)
        checks.append({"times": times, "coverage": cov, "identity": ident})
        if not (ident["ok"] and cov["covers_start"] and cov["covers_end"]):
            continue
        kept = [(t, s) for t, s in zip(times, samples) if s is not None]
        grid = build_grid(video_path, [s for _, s in kept], [t for t, _ in kept])
        if grid is None:
            checks[-1]["grid"] = "crop_failed"
            continue
        grids.append((grid, [t for t, _ in kept]))
    evidence = {"sample_plan": {"window": plan["window"], "step_sec": plan["step_sec"]}, "checks": checks}
    if len(grids) < len(plan["passes"]):
        return {"prompt_version": av.PROMPT_VERSION, "verdict": av.UNCERTAIN, "basis": "target_coverage_insufficient",
                **evidence}
    result = av.verify(grids, ask or default_ask, policy)
    return {**result, **evidence}


def observe_events(events: list[dict[str, Any]], *, ask: Callable[[bytes, str], str] | None = None,
                   detections_for: Callable[[str], list[Any]] | None = None) -> list[dict[str, Any]]:
    """Record `action_validity` on every shot that has none (in place); no-op unless the gate is enabled."""
    if not av.enabled():
        return events
    if detections_for is None:
        from pipeline.perception.runtime import load_sidecar_detections as detections_for
    cache: dict[str, list[Any]] = {}
    for event in events or []:
        if not isinstance(event, dict) or event.get("_teaser") or isinstance(event.get("action_validity"), dict):
            continue
        src = str(event.get("_src") or event.get("source_video") or event.get("source") or "")
        try:
            if src not in cache:
                cache[src] = detections_for(src) if src else []
            result = observe_event(event, src, cache[src], ask)
        except Exception as exc:                 # observation failure is UNCERTAIN, never VALID, never a crash
            result = {"prompt_version": av.PROMPT_VERSION, "verdict": av.UNCERTAIN,
                      "basis": f"observation_error:{type(exc).__name__}"}
        event.update(av.apply_to_event(event, result))
    return events

"""
pipeline/editor.py — FFmpeg reel compilation pipeline.
חותך קליפים ל-9:16, slow-mo אוטומטי ל-60fps, סדר נרטיבי, crossfade.
"""

import glob
import json
import logging
import os
import random
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import config

logger = logging.getLogger(__name__)

REEL_W, REEL_H  = 1080, 1920
XFADE_DUR       = 0.5    # חפיפה בין קליפים (שניות) — מינימום מומלץ לרילס
CLIP_FADE_DUR   = 0.25   # fade in/out בתוך קליפ
MAX_REEL_SEC    = 88     # מתחת ל-90s של Instagram Reels
SLOWMO_FPS_MIN  = 50     # fps מינימלי לslow-mo חלק (50 / 60fps)
ZOOM_MIN_HEADROOM = 1.15  # min zoom_headroom before applying any zoom
TARGET_REEL_MIN = 12     # shorter reels → warn only
TARGET_REEL_MAX = 30     # split into multiple reels when a single one would exceed this


# ── ffprobe helpers ────────────────────────────────────────────────────────

@lru_cache(maxsize=256)
def _get_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        return float(subprocess.check_output(cmd, text=True, timeout=30).strip())
    except Exception:
        return float("inf")


@lru_cache(maxsize=256)
def _get_source_fps(video_path: str) -> float:
    """מחזיר את ה-fps של הסרטון המקורי."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        raw = subprocess.check_output(cmd, text=True, timeout=15).strip()
        num, den = raw.split("/")
        return round(float(num) / float(den), 2)
    except Exception:
        return 30.0


def _clamp(start: float, end: float, video_path: str) -> tuple[float, float]:
    total = _get_duration(video_path)
    start = max(0.0, min(start, total - 4))
    end   = min(end, total)
    if end - start < 4:
        end = min(start + 4, total)
    return round(start, 2), round(end, 2)


# ── music picker ──────────────────────────────────────────────────────────

def _ensure_music_cache(music_dir: str) -> dict:
    """
    Load (or build) a BPM/energy metadata cache for all tracks in music_dir.
    Cache file: {music_dir}/.music_cache.json
    Entry invalidated when file mtime changes.
    Returns: {filename: {"bpm": float|None, "energy_score": float|None, "mtime": float}}
    """
    import json as _json

    cache_path = os.path.join(music_dir, ".music_cache.json")
    try:
        with open(cache_path) as f:
            cache = _json.load(f)
    except Exception:
        cache = {}

    files = (
        glob.glob(os.path.join(music_dir, "*.mp3")) +
        glob.glob(os.path.join(music_dir, "*.aac")) +
        glob.glob(os.path.join(music_dir, "*.m4a"))
    )

    changed = False
    for path in files:
        name  = Path(path).name
        mtime = os.path.getmtime(path)
        if name in cache and abs(cache[name].get("mtime", 0) - mtime) < 1:
            continue
        info = _analyze_music(path, 30.0)
        cache[name] = {
            "bpm":          info["bpm"],
            "energy_score": info["energy_score"],
            "mtime":        mtime,
        }
        changed = True

    if changed:
        try:
            tmp = cache_path + ".tmp"
            with open(tmp, "w") as f:
                _json.dump(cache, f)
            os.replace(tmp, cache_path)
        except Exception as e:
            logger.debug("Music cache save failed: %s", e)

    return cache


def _pick_music(sport: str = "") -> str | None:
    """Pick the best-matching music track for the given sport.
    Selection is BPM-weighted (70%) + energy-weighted (30%).
    Falls back to random.choice() if cache is empty or librosa unavailable.
    """
    music_dir = getattr(config, "MUSIC_DIR", "music")
    files = (
        glob.glob(os.path.join(music_dir, "*.mp3")) +
        glob.glob(os.path.join(music_dir, "*.aac")) +
        glob.glob(os.path.join(music_dir, "*.m4a"))
    )
    if not files:
        return None

    cache = _ensure_music_cache(music_dir)

    lo, hi  = _SPORT_BPM.get(sport.lower(), _SPORT_BPM["_default"])
    mid     = (lo + hi) / 2.0
    bpm_rng = (hi - lo) / 2.0 or 1.0

    scored: list[tuple[float, str]] = []
    for path in files:
        name  = Path(path).name
        entry = cache.get(name, {})
        bpm   = entry.get("bpm")
        eng   = entry.get("energy_score") or 0.5

        if bpm and bpm > 0:
            bpm_score = max(0.0, 1.0 - abs(bpm - mid) / (bpm_rng * 2))
        else:
            bpm_score = 0.5

        scored.append((bpm_score * 0.7 + eng * 0.3, path))

    if not scored:
        chosen = random.choice(files)
    else:
        scored.sort(reverse=True)
        top3   = [p for _, p in scored[:3]]
        chosen = random.choice(top3)

    print(f"🎵 Music: {Path(chosen).name}")
    return chosen


def _compute_cut_times(durations: list[float]) -> list[float]:
    """מחשב את זמני החיתוך (xfade offsets) בריל המורכב — קלט ליישור beats."""
    n = len(durations)
    if n <= 1:
        return []
    cuts = [round(durations[0] - XFADE_DUR, 3)]
    cumulative = durations[0] + durations[1] - XFADE_DUR
    for i in range(2, n):
        cuts.append(round(cumulative - XFADE_DUR, 3))
        cumulative += durations[i] - XFADE_DUR
    return cuts


def _analyze_music(mp3_path: str, video_duration: float,
                   cut_times: list[float] | None = None) -> dict:
    """
    Analyzes a music file and returns optimal overlay parameters for a given video duration.

    Algorithm without cut_times:
      1. Detect BPM and beat grid via librosa.
      2. Find the highest-energy window of video_duration length (the "drop").
      3. Snap start to the nearest beat on-grid.

    Algorithm with cut_times (beat-cut alignment):
      1-2 as above, then:
      3. For every beat in the top-30%-energy windows, score how well
         the beat grid aligns to the video cut timestamps.
         score = average distance from each cut to its nearest beat.
      4. Pick the start beat with the lowest score.

    Returns dict with keys:
      bpm             — detected BPM (float) or None if librosa unavailable
      start_sec       — where to start playing the track (beat-snapped)
      atempo          — FFmpeg atempo factor (0.90–1.10, or 1.0 if no stretch)
      trim_dur        — seconds to read from source (None if needs_loop)
      needs_loop      — True when track is too short even after max stretch
      energy_score    — normalized energy of the selected window [0–1]
      alignment_error — average beat-cut distance in seconds (None if no cuts given)
    """
    _default = {
        "bpm": None, "start_sec": 0.0, "atempo": 1.0,
        "trim_dur": video_duration, "needs_loop": False,
        "energy_score": None, "alignment_error": None,
    }
    try:
        import librosa
        import numpy as np
        from numpy.lib.stride_tricks import sliding_window_view
    except ImportError:
        print("  ⚠️  librosa not installed — naive music start (pip install librosa soundfile)")
        return _default

    try:
        y, sr = librosa.load(mp3_path, sr=None)
        hop_length = 512
        total_dur  = float(len(y) / sr)

        # ── BPM + beat grid ───────────────────────────────────────────────
        tempo, beat_times = librosa.beat.beat_track(
            y=y, sr=sr, units="time", hop_length=hop_length,
        )
        bpm = float(np.squeeze(tempo))

        # ── energy envelope + sliding-window means ────────────────────────
        onset_env     = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        window_frames = int(video_duration * sr / hop_length)

        if len(onset_env) > window_frames:
            windows      = sliding_window_view(onset_env, window_frames)
            window_means = windows.mean(axis=1)
        else:
            window_means = np.array([onset_env.mean()])

        max_energy = float(np.max(window_means)) + 1e-9

        # ── choose start_sec ──────────────────────────────────────────────
        alignment_error: float | None = None

        if cut_times and len(beat_times) > 0:
            # Beat-cut alignment: find beat start where beats ≈ cut timestamps
            energy_threshold = float(np.percentile(window_means, 70))
            best_score       = float("inf")
            best_start: float | None = None
            best_energy      = 0.0

            for beat_t in beat_times:
                available = total_dur - beat_t
                if available < video_duration * 0.9:
                    continue
                beat_frame = min(int(beat_t * sr / hop_length), len(window_means) - 1)
                if window_means[beat_frame] < energy_threshold:
                    continue

                atempo_cand = 1.0 if available >= video_duration else available / video_duration

                # average distance from each cut to its nearest beat
                score = sum(
                    float(np.min(np.abs(beat_times - (beat_t + ct * atempo_cand))))
                    for ct in cut_times
                ) / len(cut_times)

                if score < best_score:
                    best_score  = score
                    best_start  = beat_t
                    best_energy = float(window_means[beat_frame] / max_energy)

            if best_start is not None:
                start_sec       = float(best_start)
                alignment_error = round(best_score, 3)
            else:
                # No valid beat in high-energy window — fall back to drop
                best_frame = int(np.argmax(window_means))
                start_sec  = float(librosa.frames_to_time(best_frame, sr=sr, hop_length=hop_length))
                beats_after = beat_times[beat_times >= start_sec]
                if len(beats_after):
                    start_sec = float(beats_after[0])
                f = min(int(start_sec * sr / hop_length), len(window_means) - 1)
                best_energy = float(window_means[f] / max_energy)
        else:
            # Pure energy-based drop + beat snap
            best_frame  = int(np.argmax(window_means))
            start_sec   = float(librosa.frames_to_time(best_frame, sr=sr, hop_length=hop_length))
            beats_after = beat_times[beat_times >= start_sec]
            if len(beats_after):
                start_sec = float(beats_after[0])
            f = min(int(start_sec * sr / hop_length), len(window_means) - 1)
            best_energy = float(window_means[f] / max_energy)

        # ── compute atempo / loop flags ───────────────────────────────────
        available = total_dur - start_sec
        if available >= video_duration:
            atempo, trim_dur, needs_loop = 1.0, video_duration, False
        elif available >= video_duration * 0.9:
            atempo    = round(available / video_duration, 4)
            trim_dur  = round(available, 3)
            needs_loop = False
        else:
            atempo, trim_dur, needs_loop = 1.0, None, True

        return {
            "bpm":             round(bpm, 1),
            "start_sec":       round(start_sec, 3),
            "atempo":          atempo,
            "trim_dur":        trim_dur,
            "needs_loop":      needs_loop,
            "energy_score":    round(best_energy, 3),
            "alignment_error": alignment_error,
        }

    except Exception as e:
        logger.warning("Music analysis failed for %s: %s", Path(mp3_path).name, e)
        return _default


def analyze_music_library(video_duration: float) -> list[dict]:
    """
    סורק את MUSIC_DIR, מנתח כל שיר ומחזיר דוח כושר-הלבשה לריל באורך video_duration.
    מועיל כדי להחליט איזה שיר להכניס לספרייה ואיך הוא יתנהג.
    """
    music_dir = getattr(config, "MUSIC_DIR", "music")
    files = (
        glob.glob(os.path.join(music_dir, "*.mp3")) +
        glob.glob(os.path.join(music_dir, "*.aac")) +
        glob.glob(os.path.join(music_dir, "*.m4a"))
    )
    if not files:
        print(f"⚠️  No music files found in '{music_dir}'")
        return []

    print(f"\n🎵 Music Library Analysis — target reel: {video_duration:.0f}s")
    print(f"   Found {len(files)} track(s) in '{music_dir}'\n")

    results = []
    for path in sorted(files):
        name = Path(path).name
        info = _analyze_music(path, video_duration)

        bpm_str   = f"{info['bpm']:.0f} BPM" if info["bpm"] else "? BPM"
        start_str = f"start @ {info['start_sec']:.1f}s"
        if info["needs_loop"]:
            fit_str = "🔁 loop needed (track too short)"
        elif abs(info["atempo"] - 1.0) < 0.005:
            fit_str = "✅ perfect fit"
        elif info["atempo"] < 1.0:
            pct = round((1 - info["atempo"]) * 100, 1)
            fit_str = f"🐌 slow down {pct}% to fill reel"
        else:
            pct = round((info["atempo"] - 1) * 100, 1)
            fit_str = f"⚡ speed up {pct}% to trim to reel"

        energy_str = f"energy={info['energy_score']:.2f}" if info["energy_score"] is not None else ""
        align_str  = (f"cuts±{info['alignment_error']:.2f}s" if info.get("alignment_error") is not None
                      else "[energy-based, no cut data]")
        print(f"  🎵 {name}")
        print(f"     {bpm_str} · {start_str} · {fit_str} · {energy_str} · {align_str}")
        results.append({"file": name, **info})

    return results

# ── Sport-specific color grade presets ────────────────────────────────────
_COLOR_PROFILES: dict[str, str] = {
    "surfing":       "eq=contrast=1.18:saturation=1.40:brightness=0.03",
    "swimming":      "eq=contrast=1.15:saturation=1.30:brightness=0.04",
    "football":      "eq=contrast=1.12:saturation=1.18:brightness=0.01",
    "soccer":        "eq=contrast=1.12:saturation=1.18:brightness=0.01",
    "basketball":    "eq=contrast=1.08:saturation=1.12:brightness=0.03",
    "skateboarding": "eq=contrast=1.22:saturation=1.20:brightness=-0.02",
    "skiing":        "eq=contrast=1.20:saturation=1.15:brightness=0.05",
    "snowboarding":  "eq=contrast=1.20:saturation=1.18:brightness=0.05",
    "parkour":       "eq=contrast=1.15:saturation=1.20:brightness=-0.01",
    "cycling":       "eq=contrast=1.10:saturation=1.22:brightness=0.02",
    "motocross":     "eq=contrast=1.18:saturation=1.25:brightness=-0.01",
    "_default":      "eq=contrast=1.12:saturation=1.22:brightness=0.02",
}


# ── Sport-specific xfade transition presets ────────────────────────────────
_SPORT_XFADES: dict[str, list[str]] = {
    "surfing":       ["slideleft", "slideright", "zoomin"],
    "skateboarding": ["zoomin",    "pixelize",   "slideleft"],
    "snowboarding":  ["fadewhite", "slidedown",  "slideleft"],
    "skiing":        ["fadewhite", "slideleft",  "slideright"],
    "football":      ["slideleft", "wipeleft",   "slideright"],
    "soccer":        ["slideleft", "wipeleft",   "slideright"],
    "basketball":    ["wipeleft",  "slideleft",  "slideright"],
    "cycling":       ["slideleft", "wiperight",  "slideright"],
    "motocross":     ["slideleft", "zoomin",     "wipeleft"],
    "parkour":       ["zoomin",    "slideleft",  "pixelize"],
    "_default":      ["slideleft", "slideright", "fade"],
}

_SPORT_BPM: dict[str, tuple[int, int]] = {
    "surfing":       (85,  120),
    "swimming":      (80,  115),
    "skateboarding": (120, 160),
    "skiing":        (100, 130),
    "snowboarding":  (100, 130),
    "football":      (120, 145),
    "soccer":        (120, 145),
    "basketball":    (115, 140),
    "cycling":       (110, 135),
    "motocross":     (130, 165),
    "parkour":       (120, 150),
    "_default":      (100, 140),
}


def _find_font() -> str | None:
    """Find a bold system font for drawtext overlays. Returns None if unavailable."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial Bold.ttf",
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def _partition_events(
    events: list[dict],
    slowmo: bool,
    target_max: float = TARGET_REEL_MAX,
) -> list[list[dict]]:
    """
    Split events into reel-sized partitions (each ≤ target_max seconds).
    Events are sorted by score descending so each reel gets the best remaining events.
    Returns a list of event groups; each group is then narrative-ordered independently.

    Duration estimate per event:
      slowmo source → event_dur × 1.4  (speed-ramp: 0.3+0.8+0.3)
      normal source → event_dur × 1.0
    Xfade subtracts XFADE_DUR per transition.
    """
    if not events:
        return []

    factor = 1.4 if slowmo else 1.0

    def _clip_dur(ev: dict) -> float:
        return (ev["end"] - ev["start"]) * factor

    def _group_dur(grp: list[dict]) -> float:
        return sum(_clip_dur(e) for e in grp) - XFADE_DUR * (len(grp) - 1)

    # Best events first → each reel gets the highest-quality moments available
    remaining = sorted(events, key=lambda e: e["score"], reverse=True)

    partitions: list[list[dict]] = []
    current: list[dict] = []

    for ev in remaining:
        test = current + [ev]
        if current and _group_dur(test) > target_max:
            partitions.append(current)
            current = [ev]
        else:
            current = test

    if current:
        partitions.append(current)

    if len(partitions) > 1:
        logger.info(
            "Events split into %d reels (total %d events, est. %.0fs total)",
            len(partitions), len(events),
            sum(_group_dur(p) for p in partitions),
        )
    return partitions


def _narrative_order(events: list[dict]) -> list[dict]:
    """
    מסדר קליפים לפי עקרון narrative arc:
      פתיחה חזקה (2nd best) → בנייה עולה → שיא (best) בסוף.

    מחקרים על רשתות חברתיות: הצופה זוכר את הקליפ הראשון והאחרון.
    לכן: opener חזק ← build ← CLIMAX.
    """
    if len(events) <= 2:
        # 1-2 קליפים: מהנמוך לגבוה (עולה לסיום)
        return sorted(events, key=lambda e: e["score"])

    by_score = sorted(events, key=lambda e: e["score"], reverse=True)
    opener   = by_score[1]                                           # 2nd best → hook ראשון
    climax   = by_score[0]                                           # best → שיא אחרון
    middle   = sorted(by_score[2:], key=lambda e: e["score"])       # שאר בסדר עולה

    return [opener] + middle + [climax]


def _get_source_info(video_path: str) -> dict:
    """Detect source resolution and FPS; compute zoom headroom and slowmo capability."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "json", video_path],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        s    = data["streams"][0]
        w, h = int(s["width"]), int(s["height"])
        num, den = s["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        zoom_headroom = w / 1920  # 4K=2.0, 1080p=1.0, 720p=0.67
        return {"width": w, "height": h, "fps": round(fps, 1),
                "zoom_headroom": round(zoom_headroom, 2),
                "can_slowmo": fps >= SLOWMO_FPS_MIN}
    except Exception as e:
        logger.debug("_get_source_info failed for %s: %s", video_path, e)
        return {"width": 1920, "height": 1080, "fps": 30.0,
                "zoom_headroom": 1.0, "can_slowmo": False}


# ── שלב 1: חיתוך קליפ בודד ────────────────────────────────────────────────

def cut_clip(
    video_path: str,
    event: dict,
    index: int,
    slowmo: bool = False,
    sport: str = "",
    source_info: dict | None = None,
) -> str | None:
    """
    חותך רגע שיא:
    - 9:16 zoom-crop ממורכז על האתלט לפי crop_x
    - zoom adapts to source resolution (4K→up to 1.8×, 1080p→1.0×)
    - Gemini edit_hints (event["edit"]) set artistic intent; source_info caps technically
    - slow-mo speed-ramp if source fps >= SLOWMO_FPS_MIN
    - sport-specific color grade + fade
    - ללא אודיו
    """
    start, end = _clamp(event["start"], event["end"], video_path)
    input_dur  = end - start
    event_type = event.get("type", "highlight")

    if (event["start"], event["end"]) != (start, end):
        logger.warning("⚠️ Timestamps clamped [%.1f,%.1f]→[%.1f,%.1f]",
                       event["start"], event["end"], start, end)

    # ── Three-layer edit decisions: zoom + focus + slowmo ────────────────────
    # Layer 1: Gemini's artistic direction
    edit_hints     = event.get("edit") or {}
    requested_zoom = float(edit_hints.get("zoom", 1.0))
    requested_sm   = bool(edit_hints.get("slowmo", slowmo))
    focus          = str(edit_hints.get("focus", "full")).lower()
    score          = int(event.get("score", 7))

    # Layer 2: source quality constraints (technical ceiling)
    if source_info is None:
        source_info = _get_source_info(video_path)
    zoom_headroom = source_info.get("zoom_headroom", 1.0)
    can_slowmo    = source_info.get("can_slowmo", True)

    # Merge zoom: artistic intent capped by technical ceiling
    if zoom_headroom >= ZOOM_MIN_HEADROOM:
        applied_zoom = min(requested_zoom, zoom_headroom * 0.9)
        applied_zoom = max(1.0, applied_zoom)
    else:
        applied_zoom = 1.0
        if requested_zoom > 1.1:
            logger.debug("Zoom ×%.1f requested but headroom only ×%.2f — no zoom applied",
                         requested_zoom, zoom_headroom)
    use_slowmo = requested_sm and can_slowmo
    if requested_sm and not can_slowmo:
        logger.warning("slowmo requested but source %.0ffps < %dfps — skipping speed-ramp",
                       source_info.get("fps", 0), SLOWMO_FPS_MIN)

    # Score-based slowmo depth: higher score → longer, deeper slow-motion
    if use_slowmo:
        if score >= 9:
            sm_frac, sm_pts_expr = 0.50, "2.5*(PTS-STARTPTS)"  # 50% center at 0.4×
        elif score >= 7:
            sm_frac, sm_pts_expr = 0.40, "2*(PTS-STARTPTS)"    # 40% center at 0.5×
        else:
            sm_frac, sm_pts_expr = 0.30, "1.5*(PTS-STARTPTS)"  # 30% center at 0.67×
        slow_factor = float(sm_pts_expr.split("*")[0])
    else:
        sm_frac, sm_pts_expr, slow_factor = 0.40, "PTS-STARTPTS", 1.0

    # Log non-trivial edit decisions
    if applied_zoom > 1.05 or use_slowmo != slowmo:
        zoom_str = f"zoom×{applied_zoom:.1f}[{focus}]" if applied_zoom > 1.05 else "zoom×1.0"
        sm_str   = f"slowmo[score={score}]" if use_slowmo else "no-slowmo"
        print(f"  📐 {zoom_str} (headroom×{zoom_headroom:.1f}) | {sm_str}")

    # ── Crop filter strings ────────────────────────────────────────────────
    crop_x = max(0.0, min(1.0, float(event.get("crop_x", 0.5))))
    crop_y = max(0.0, min(1.0, float(event.get("crop_y", 0.65))))

    # Wide (1.0×): scale to REEL_H height, crop REEL_W wide centred on crop_x
    half_w  = REEL_W // 2
    fg_wide = (
        f"scale=iw*{REEL_H}/ih:{REEL_H},"
        f"crop={REEL_W}:{REEL_H}:"
        f"'max(0,min(iw-{REEL_W},trunc(iw*{crop_x:.4f}-{half_w})))':0"
    )

    # Zoomed: crop smaller region then scale up; crop_y positions athlete vertically
    if applied_zoom > 1.05:
        crop_w      = int(REEL_W / applied_zoom)
        crop_h      = int(REEL_H / applied_zoom)
        half_crop_w = crop_w // 2
        y_center    = int(crop_y * REEL_H)
        y_offset    = max(0, min(REEL_H - crop_h, y_center - crop_h // 2))
        fg_zoom = (
            f"scale=iw*{REEL_H}/ih:{REEL_H},"
            f"crop={crop_w}:{crop_h}:"
            f"'max(0,min(iw-{crop_w},trunc(iw*{crop_x:.4f}-{half_crop_w})))':{y_offset},"
            f"scale={REEL_W}:{REEL_H}"
        )
    else:
        fg_zoom = fg_wide  # no zoom headroom — fall back to wide

    # ── Foreground pipeline + speed ramp ──────────────────────────────────
    grade = _COLOR_PROFILES.get(sport.lower(), _COLOR_PROFILES["_default"])

    use_peak_focus = focus == "peak" and applied_zoom > 1.05

    if use_peak_focus:
        # 3-section pipeline: wide | zoomed (+ optional slowmo) | wide
        # Zoom sections always 30%/40%/30%; slowmo applies only to middle.
        pk_t1 = round(input_dur * 0.30, 3)
        pk_t2 = round(input_dur * 0.70, 3)
        mid_pts = sm_pts_expr if use_slowmo else "PTS-STARTPTS"
        fg_section = (
            f"[fg_in]split=3[f1][f2][f3];"
            f"[f1]trim=0:{pk_t1},setpts=PTS-STARTPTS,{fg_wide}[fs1];"
            f"[f2]trim={pk_t1}:{pk_t2},setpts={mid_pts},{fg_zoom}[fs2];"
            f"[f3]trim={pk_t2}:{input_dur:.3f},setpts=PTS-STARTPTS,{fg_wide}[fs3];"
            f"[fs1][fs2][fs3]concat=n=3:v=1:a=0[fg]"
        )
        # output_dur = pre + zoomed_middle * slow_factor + post
        output_dur = round(pk_t1 + (pk_t2 - pk_t1) * slow_factor + (input_dur - pk_t2), 3)
        overlay_sink = ","
        ramp         = ""
    else:
        fg_section   = None
        fg_crop      = fg_zoom if applied_zoom > 1.05 else fg_wide
        if use_slowmo:
            t1 = round(input_dur * (0.5 - sm_frac / 2), 3)
            t2 = round(input_dur * (0.5 + sm_frac / 2), 3)
            overlay_sink = "[merged];"
            ramp = (
                f"[merged]split=3[s1_in][s2_in][s3_in];"
                f"[s1_in]trim=0:{t1},setpts=PTS-STARTPTS[s1];"
                f"[s2_in]trim={t1}:{t2},setpts={sm_pts_expr}[s2];"
                f"[s3_in]trim={t2}:{input_dur:.3f},setpts=PTS-STARTPTS[s3];"
                f"[s1][s2][s3]concat=n=3:v=1:a=0[ramped];"
                f"[ramped]"
            )
        else:
            overlay_sink = ","
            ramp         = ""
        output_dur = round(input_dur * ((1 - sm_frac) + sm_frac * slow_factor), 3)

    clip_fade = min(CLIP_FADE_DUR, output_dur / 6)

    os.makedirs(config.TMP_DIR, exist_ok=True)
    out = os.path.join(config.TMP_DIR, f"{Path(video_path).stem}_clip{index:02d}.mp4")

    # ── Assemble full FFmpeg filter_complex ───────────────────────────────
    bg_filter = (
        f"[bg_in]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
        f"crop={REEL_W}:{REEL_H},gblur=sigma=25:steps=2[bg]"
    )
    post_grade = (
        f"{grade},"
        f"unsharp=5:5:0.65,"
        f"fade=t=in:st=0:d={clip_fade:.2f},"
        f"fade=t=out:st={output_dur - clip_fade:.2f}:d={clip_fade:.2f}"
        f"[out]"
    )

    if use_peak_focus:
        vf = (
            f"[0:v]split[bg_in][fg_in];"
            f"{bg_filter};"
            f"{fg_section};"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"{post_grade}"
        )
    else:
        vf = (
            f"[0:v]split[bg_in][fg_in];"
            f"{bg_filter};"
            f"[fg_in]{fg_crop}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{overlay_sink}"
            f"{ramp}"
            f"{post_grade}"
        )

    slowmo_tag = " [🐢 speed-ramp]" if use_slowmo else ""
    print(f"🎬 Clip {index}: {start:.1f}s→{end:.1f}s [{event_type}] "
          f"({input_dur:.1f}s in / {output_dur:.1f}s out){slowmo_tag}")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(input_dur),       # input option: read exactly input_dur from source
        "-i", video_path,
        "-filter_complex", vf,
        "-map", "[out]",
        "-t", str(output_dur),      # output option: cap at output_dur (2× for slow-mo)
        "-an",
        "-c:v", "libx264",
        "-profile:v", "high",       # H.264 High Profile — תקן ל-1080p
        "-crf", "20",
        "-preset", "fast",
        "-r", "30",
        "-g", "60",                 # GOP = 2s @ 30fps — תקן Azure/Teams (default של FFmpeg 250f ≈ 8s)
        "-pix_fmt", "yuv420p",      # 4:2:0 chroma subsampling — חובה לאינסטגרם
        "-colorspace", "bt709",     # BT.709 — תקן Microsoft ל-HD מעל 720p
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-movflags", "+faststart",
        out,
    ]

    def _remove_partial() -> None:
        try: os.remove(out)
        except OSError: pass

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            logger.error("FFmpeg clip %d: %s", index, r.stderr[-1500:])
            print(f"❌ Clip {index} failed: {r.stderr[-300:]}")
            _remove_partial()
            return None
        return out
    except subprocess.TimeoutExpired:
        print(f"❌ Clip {index} timed out")
        _remove_partial()
        return None
    except FileNotFoundError:
        print("❌ FFmpeg not found — install: sudo apt install ffmpeg")
        return None
    except Exception as e:
        logger.error("Clip %d unexpected: %s", index, e)
        _remove_partial()
        return None


# ── שלב 2: compilation לריל אחד ──────────────────────────────────────────

_TRANSITION_MAP: dict[str, str] = {
    "cut":   "fadeblack",   # near-instant (0.1s) — high-impact moments
    "fade":  "fade",        # soft cross-fade — calm/flowing moments
    "slide": "slideleft",   # slide — general purpose
    "zoom":  "zoomin",      # zoom-in — building intensity before climax
}


def _xfade_filter(
    n: int,
    durations: list[float],
    sport: str = "",
    transitions: list[str] | None = None,
) -> str:
    """Build xfade filter_complex between n clips.
    transitions: optional list[str] of Gemini transition_out values per clip.
    Uses sport-specific random pool as fallback when not provided.
    """
    if n == 1:
        return "[0:v]null[xfout]"

    _options = _SPORT_XFADES.get(sport.lower(), _SPORT_XFADES["_default"])

    def _pick(i: int) -> str:
        if transitions and i < len(transitions):
            return _TRANSITION_MAP.get(transitions[i], "slideleft")
        return random.choice(_options)

    parts      = []
    offset     = round(durations[0] - XFADE_DUR, 3)
    out_lbl    = "[xfout]" if n == 2 else "[xf1]"
    parts.append(
        f"[0:v][1:v]xfade=transition={_pick(0)}:duration={XFADE_DUR}:offset={offset}{out_lbl}"
    )

    cumulative = durations[0] + durations[1] - XFADE_DUR
    for i in range(2, n):
        offset  = round(cumulative - XFADE_DUR, 3)
        prev    = "[xf1]" if i == 2 else f"[xf{i-1}]"
        out_lbl = "[xfout]" if i == n - 1 else f"[xf{i}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition={_pick(i-1)}:duration={XFADE_DUR}:offset={offset}{out_lbl}"
        )
        cumulative += durations[i] - XFADE_DUR

    return ";".join(parts)


def compile_reel(
    clip_paths: list[str],
    logo_path: str,
    output_path: str,
    sport: str = "",
    athlete_label: str = "",
    music_path: str | None = None,
    transitions: list[str] | None = None,
) -> str | None:
    """מחבר קליפים לריל אחד עם xfade + לוגו watermark + כותרת תחתית."""
    n = len(clip_paths)
    if n == 0:
        return None

    with ThreadPoolExecutor(max_workers=min(n, config.MAX_CUT_WORKERS)) as _pool:
        durations = list(_pool.map(_get_duration, clip_paths))
    total_dur = sum(durations) - XFADE_DUR * (n - 1)

    if total_dur > MAX_REEL_SEC:
        logger.warning("⚠️ Reel %.0fs > 90s Instagram limit", total_dur)
        print(f"⚠️ Reel {total_dur:.0f}s — exceeds Instagram 90s limit")

    inputs   = []
    for p in clip_paths:
        inputs += ["-i", p]

    has_logo = logo_path and Path(logo_path).exists()
    logo_idx = n
    if has_logo:
        inputs += ["-i", logo_path]

    xfade_f = _xfade_filter(n, durations, sport=sport, transitions=transitions)

    if has_logo:
        logo_w = REEL_W // 13
        logo_f = (
            f"[{logo_idx}:v]scale={logo_w}:-1,format=rgba,"
            f"colorchannelmixer=aa=0.85[logo];"
            f"[xfout][logo]overlay=W-w-20:H-h-20[final]"
        )
        filter_complex = xfade_f + ";" + logo_f
        map_out = "[final]"
    else:
        filter_complex = xfade_f
        map_out = "[xfout]"

    # Athlete lower-third text overlay (first 2.8s, fade in+out)
    display_text = athlete_label[:25].strip()
    font_path    = _find_font()
    if display_text and font_path:
        safe_text  = display_text.replace("'", "\\'").replace(":", "\\:")
        prev_label = map_out.strip("[]")
        drawtext_f = (
            f"[{prev_label}]drawtext="
            f"fontfile={font_path}:"
            f"text='{safe_text}':"
            f"fontsize=52:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw=10:"
            f"x=(w-text_w)/2:y=h-260:"
            f"enable='between(t,0.3,2.8)':"
            f"alpha='if(lt(t,0.6),(t-0.3)/0.3,"
            f"if(gt(t,2.5),(2.8-t)/0.3,1))'[captioned]"
        )
        filter_complex += ";" + drawtext_f
        map_out = "[captioned]"

    cut_times = _compute_cut_times(durations)
    has_music = bool(music_path)
    music_idx  = n + (1 if has_logo else 0)
    if has_music:
        mx        = _analyze_music(music_path, total_dur, cut_times=cut_times)
        fade_st   = max(0.0, total_dur - 2.0)
        audio_pre = "dynaudnorm=p=0.95:m=30,afade=t=in:st=0:d=1.5,"

        if mx["needs_loop"]:
            audio_f = (
                f"atrim=start={mx['start_sec']:.3f},"
                f"aloop=loop=-1:size=2000000000,"
                f"atrim=duration={total_dur:.3f},"
                f"{audio_pre}"
                f"afade=t=out:st={fade_st:.3f}:d=2"
            )
        elif abs(mx["atempo"] - 1.0) > 0.005:
            audio_f = (
                f"atrim=start={mx['start_sec']:.3f}:duration={mx['trim_dur']:.3f},"
                f"atempo={mx['atempo']:.4f},"
                f"{audio_pre}"
                f"afade=t=out:st={fade_st:.3f}:d=2"
            )
        else:
            audio_f = (
                f"atrim=start={mx['start_sec']:.3f}:duration={total_dur:.3f},"
                f"{audio_pre}"
                f"afade=t=out:st={fade_st:.3f}:d=2"
            )

        inputs += ["-i", music_path]
        filter_complex += f";[{music_idx}:a]{audio_f}[aout]"

        bpm_str   = f"{mx['bpm']:.0f}bpm" if mx["bpm"] else "?"
        fit_label = ("loop" if mx["needs_loop"]
                     else f"×{mx['atempo']:.3f}" if abs(mx["atempo"] - 1.0) > 0.005
                     else "exact")
        align_str = (f", cuts±{mx['alignment_error']:.2f}s"
                     if mx["alignment_error"] is not None else "")
        print(f"🎵 {Path(music_path).name} — {bpm_str}, sync@{mx['start_sec']:.1f}s{align_str}, {fit_label}")

    music_tag = f" + 🎵 {Path(music_path).name}" if has_music else ""
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", map_out,
        *(["-map", "[aout]"] if has_music else ["-an"]),
        "-c:v", "libx264",
        "-profile:v", "high",       # H.264 High Profile — תקן ל-1080p
        "-crf", "18",
        "-preset", "fast",
        "-r", "30",
        "-g", "60",                 # GOP = 2s @ 30fps — תקן Azure/Teams
        "-pix_fmt", "yuv420p",      # 4:2:0 chroma subsampling — חובה לאינסטגרם
        "-colorspace", "bt709",     # BT.709 — תקן Microsoft ל-HD מעל 720p
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        *(["-c:a", "aac", "-b:a", "192k", "-ar", "44100"] if has_music else []),
        "-movflags", "+faststart",
        output_path,
    ]

    print(f"🎬 Compiling: {n} clip(s), {total_dur:.0f}s → {Path(output_path).name}{music_tag}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            logger.error("Reel compile: %s", r.stderr[-2000:])
            print(f"❌ Compile failed: {r.stderr[-400:]}")
            return None

        size_mb = os.path.getsize(output_path) / 1_000_000
        print(f"✅ Reel ready: {output_path} ({size_mb:.1f} MB, {total_dur:.0f}s)")
        return output_path

    except subprocess.TimeoutExpired:
        print("❌ Compilation timed out")
        return None
    except Exception as e:
        logger.error("Reel compile unexpected: %s", e)
        return None


def compile_multi_source_reel(appearances: list[dict], sport: str = "",
                               athlete_label: str = "") -> list[str]:
    """
    Creates reels for one athlete using clips that may come from different source videos.

    Args:
        appearances:    list of {"path": source_video_path, "events": [...]}
        sport:          activity label for color grading (e.g. "surfing", "football")
        athlete_label:  short athlete description for lower-third text overlay

    Returns list of compiled reel paths (one per partition; may be multiple if athlete
    has many high-scoring events that would exceed TARGET_REEL_MAX in a single reel).
    """
    if not appearances:
        return []

    # Attach source path to each event so we can look it up after narrative ordering
    all_events: list[dict] = []
    for app in appearances:
        for ev in app["events"]:
            all_events.append({**ev, "_src": app["path"]})

    if not all_events:
        return []

    first_src      = appearances[0]["path"]
    slowmo_capable = _get_source_fps(first_src) >= SLOWMO_FPS_MIN
    partitions     = _partition_events(all_events, slowmo_capable)
    first_stem     = Path(appearances[0]["path"]).stem
    reels: list[str] = []

    for part_idx, part_events in enumerate(partitions):
        ordered           = _narrative_order(part_events)
        event_transitions = [ev.get("edit", {}).get("transition_out", "slide") for ev in ordered]
        idx_base          = 91 + part_idx * 50

        # Extract _src before submitting to thread pool (pop is not thread-safe on shared dict)
        tasks = []
        src_info_cache: dict[str, dict] = {}
        for i, event in enumerate(ordered):
            src    = event.pop("_src")
            if src not in src_info_cache:
                src_info_cache[src] = _get_source_info(src)
            si     = src_info_cache[src]
            slowmo = si["can_slowmo"]
            tasks.append((i, src, event, slowmo, si))

        clip_paths = []
        with ThreadPoolExecutor(max_workers=config.MAX_CUT_WORKERS) as pool:
            future_map = {
                pool.submit(cut_clip, src, ev, idx_base + i, sw, sport, si): i
                for i, src, ev, sw, si in tasks
            }
            results: dict[int, str] = {}
            for fut, i in future_map.items():
                clip = fut.result()
                if clip:
                    results[i] = clip
        clip_paths = [results[i] for i in sorted(results)]

        if not clip_paths:
            continue

        suffix    = f"_p{part_idx + 1}" if len(partitions) > 1 else ""
        reel_stem = f"MULTI_{first_stem}{suffix}"
        reel_path = os.path.join(config.TMP_DIR, f"{reel_stem}.mp4")

        # Cache clips for add_music.py beat-sync step
        cached_clips_m: list[str] = []
        try:
            cache_dir_m = os.path.join(config.CLIPS_CACHE_DIR, reel_stem)
            os.makedirs(cache_dir_m, exist_ok=True)
            for cp in clip_paths:
                dst = os.path.join(cache_dir_m, Path(cp).name)
                shutil.copy2(cp, dst)
                cached_clips_m.append(dst)
            first_si = next(iter(src_info_cache.values())) if src_info_cache else {}
            meta_m = {
                "events":         ordered,
                "sport":          sport,
                "athlete_label":  athlete_label,
                "clip_paths":     cached_clips_m,
                "source_quality": first_si,
            }
            with open(os.path.join(cache_dir_m, f"{reel_stem}.meta.json"), "w") as _mf:
                json.dump(meta_m, _mf, ensure_ascii=False, indent=2)
        except Exception as _ce:
            logger.warning("Clips cache failed (multi): %s", _ce)

        try:
            reel = compile_reel(clip_paths, config.LOGO_PATH, reel_path,
                                sport=sport, athlete_label=athlete_label,
                                transitions=event_transitions)
        finally:
            for p in clip_paths:
                try: os.remove(p)
                except OSError: pass

        if reel:
            reels.append(reel)

    return reels


def create_preview(reel_path: str, athlete_label: str = "") -> str:
    """
    Generate a full-quality watermarked preview from an approved reel.

    Resolution, frame-rate and audio are preserved exactly.  Only a
    PREVIEW ONLY watermark (+ optional athlete name) is burned in via
    drawtext so the video is clearly not the paid deliverable.

    Returns the path of the generated preview file (same dir, _preview suffix).
    """
    out = reel_path.replace(".mp4", "_preview.mp4")

    # Strip FFmpeg drawtext metacharacters from the label
    safe = re.sub(r"[^A-Za-z0-9 #.,_-]", "", athlete_label)[:40].strip()

    dt_top = (
        "drawtext=text='PREVIEW ONLY':"
        "fontsize=h/8:"
        "fontcolor=white@0.85:"
        "x=(w-text_w)/2:y=(h/2 - text_h - 8):"
        "box=1:boxcolor=black@0.5:boxborderw=14:"
        "shadowx=2:shadowy=2"
    )
    if safe:
        dt_name = (
            f"drawtext=text='{safe}':"
            "fontsize=h/16:"
            "fontcolor=white@0.75:"
            "x=(w-text_w)/2:y=(h/2 + 8):"
            "box=1:boxcolor=black@0.4:boxborderw=8"
        )
        vf = f"{dt_top},{dt_name}"
    else:
        vf = dt_top

    cmd = [
        "ffmpeg", "-y", "-i", reel_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "copy",
        out,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Preview generation failed: {result.stderr.decode(errors='replace')[:400]}"
        )
    return out


# ── ממשק ראשי ─────────────────────────────────────────────────────────────

def create_reel(video_path: str, events: list[dict], sport: str = "",
                athlete_label: str = "") -> list[str]:
    """
    מקבל סרטון גולמי + events מ-Gemini.
    מחזיר רשימת ריל 9:16 מוכנים להעלאה (אחד או יותר אם ה-events עוברים את TARGET_REEL_MAX).
    """
    print(f"\n🎬 Creating reel from '{Path(video_path).name}' ({len(events)} event(s))")

    # 1. בדיקת fps + רזולוציה (לפני partition כדי שנדע את הfactor הנכון)
    src_info   = _get_source_info(video_path)
    source_fps = src_info["fps"]
    slowmo     = src_info["can_slowmo"]
    if slowmo:
        print(f"🐢 Source {source_fps:.0f}fps — slow-mo 50% enabled")
    else:
        print(f"⚡ Source {source_fps:.0f}fps — slow-mo skipped (need {SLOWMO_FPS_MIN}+fps)")
    if src_info["zoom_headroom"] >= ZOOM_MIN_HEADROOM:
        print(f"🔍 Source {src_info['width']}×{src_info['height']} — zoom headroom ×{src_info['zoom_headroom']:.1f}")

    # 2. פיצול events לפרטישנים (כל פרטישן ≤ TARGET_REEL_MAX שניות)
    partitions = _partition_events(events, slowmo)
    if len(partitions) > 1:
        print(f"📦 {len(events)} events → {len(partitions)} reels (≤{TARGET_REEL_MAX}s each)")

    sport_tag = f"_{sport}" if sport else ""
    reels: list[str] = []

    for part_idx, part_events in enumerate(partitions):
        # 3. סדר נרטיבי לכל פרטישן
        ordered = _narrative_order(part_events)
        order_log = " → ".join(f"{e['type']}({e['score']})" for e in ordered)
        print(f"📋 Reel {part_idx + 1}/{len(partitions)} narrative: {order_log}")
        event_transitions = [ev.get("edit", {}).get("transition_out", "slide") for ev in ordered]

        # 4. חיתוך קליפים במקביל
        idx_base   = part_idx * 50 + 1
        clip_paths = []
        with ThreadPoolExecutor(max_workers=config.MAX_CUT_WORKERS) as pool:
            future_map = {
                pool.submit(cut_clip, video_path, ev, idx_base + i, slowmo, sport, src_info): i
                for i, ev in enumerate(ordered)
            }
            results: dict[int, str] = {}
            for fut, i in future_map.items():
                clip = fut.result()
                if clip:
                    results[i] = clip
                else:
                    print(f"⚠️ Event {i} ({ordered[i].get('type')}) skipped")
        clip_paths = [results[i] for i in sorted(results)]

        if not clip_paths:
            print(f"❌ Reel {part_idx + 1}: no clips produced")
            continue

        # 5. compilation
        suffix    = f"_p{part_idx + 1}" if len(partitions) > 1 else ""
        reel_stem = f"REEL_{Path(video_path).stem}{sport_tag}{suffix}"
        reel_path = os.path.join(config.TMP_DIR, f"{reel_stem}.mp4")

        # Cache clips for add_music.py beat-sync step
        cached_clips: list[str] = []
        try:
            cache_dir = os.path.join(config.CLIPS_CACHE_DIR, reel_stem)
            os.makedirs(cache_dir, exist_ok=True)
            for cp in clip_paths:
                dst = os.path.join(cache_dir, Path(cp).name)
                shutil.copy2(cp, dst)
                cached_clips.append(dst)
            meta = {
                "events":         ordered,
                "sport":          sport,
                "athlete_label":  athlete_label,
                "clip_paths":     cached_clips,
                "source_quality": src_info,
            }
            with open(os.path.join(cache_dir, f"{reel_stem}.meta.json"), "w") as _mf:
                json.dump(meta, _mf, ensure_ascii=False, indent=2)
        except Exception as _ce:
            logger.warning("Clips cache failed: %s", _ce)

        try:
            reel = compile_reel(clip_paths, config.LOGO_PATH, reel_path,
                                sport=sport, athlete_label=athlete_label,
                                transitions=event_transitions)
        finally:
            for p in clip_paths:
                try: os.remove(p)
                except OSError: pass

        if reel:
            reels.append(reel)

    return reels

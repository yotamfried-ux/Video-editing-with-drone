"""
pipeline/editor.py — FFmpeg reel compilation pipeline.
חותך קליפים ל-9:16, slow-mo אוטומטי ל-60fps, סדר נרטיבי, crossfade.
"""

import glob
import logging
import os
import random
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)

REEL_W, REEL_H = 1080, 1920
XFADE_DUR      = 0.5    # חפיפה בין קליפים (שניות) — מינימום מומלץ לרילס
CLIP_FADE_DUR  = 0.25   # fade in/out בתוך קליפ
MAX_REEL_SEC   = 88     # מתחת ל-90s של Instagram Reels
SLOWMO_FPS_MIN = 50     # fps מינימלי לslow-mo חלק (50 / 60fps)


# ── ffprobe helpers ────────────────────────────────────────────────────────

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

def _pick_music() -> str | None:
    """בוחר אקראית קובץ מוזיקה מ-MUSIC_DIR. מחזיר None אם התיקייה ריקה/לא קיימת."""
    music_dir = getattr(config, "MUSIC_DIR", "music")
    files = (
        glob.glob(os.path.join(music_dir, "*.mp3")) +
        glob.glob(os.path.join(music_dir, "*.aac")) +
        glob.glob(os.path.join(music_dir, "*.m4a"))
    )
    if not files:
        return None
    chosen = random.choice(files)
    print(f"🎵 Music: {Path(chosen).name}")
    return chosen


def _analyze_music(mp3_path: str, video_duration: float) -> dict:
    """
    Analyzes a music file and returns optimal overlay parameters for a given video duration.

    Algorithm:
      1. Detect BPM and beat grid via librosa.
      2. Find the highest-energy window of video_duration length (the "drop").
      3. Snap start to the nearest beat on-grid.
      4. Compute atempo factor if available audio is slightly off (±10% max).

    Returns dict with keys:
      bpm         — detected BPM (float) or None if librosa unavailable
      start_sec   — where to start playing the track (beat-snapped)
      atempo      — FFmpeg atempo factor (0.90–1.10, or 1.0 if no stretch needed)
      trim_dur    — seconds to read from source before atempo (None if needs_loop)
      needs_loop  — True when track is too short even after max stretch
      energy_score — normalized energy of the selected window [0–1]
    """
    _default = {
        "bpm": None, "start_sec": 0.0, "atempo": 1.0,
        "trim_dur": video_duration, "needs_loop": False, "energy_score": None,
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
        total_dur = float(len(y) / sr)

        # ── BPM + beats ───────────────────────────────────────────────────
        tempo, beat_times = librosa.beat.beat_track(
            y=y, sr=sr, units="time", hop_length=hop_length,
        )
        bpm = float(np.squeeze(tempo))

        # ── highest-energy window (the "drop") ────────────────────────────
        onset_env    = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        window_frames = int(video_duration * sr / hop_length)

        if len(onset_env) > window_frames:
            windows      = sliding_window_view(onset_env, window_frames)
            window_means = windows.mean(axis=1)
            best_frame   = int(np.argmax(window_means))
            energy_score = float(window_means[best_frame] / (np.max(window_means) + 1e-9))
        else:
            best_frame   = 0
            energy_score = 1.0

        start_sec = float(librosa.frames_to_time(best_frame, sr=sr, hop_length=hop_length))

        # ── snap start to nearest beat ────────────────────────────────────
        beats_after = beat_times[beat_times >= start_sec]
        if len(beats_after):
            start_sec = float(beats_after[0])

        available = total_dur - start_sec

        if available >= video_duration:
            # Track long enough — trim exactly, no stretch
            return {
                "bpm": round(bpm, 1), "start_sec": round(start_sec, 3),
                "atempo": 1.0,        "trim_dur": video_duration,
                "needs_loop": False,  "energy_score": round(energy_score, 3),
            }
        elif available >= video_duration * 0.9:
            # Slightly short — slow down ≤10% to fill the reel
            atempo = round(available / video_duration, 4)  # < 1.0
            return {
                "bpm": round(bpm, 1), "start_sec": round(start_sec, 3),
                "atempo": atempo,     "trim_dur": round(available, 3),
                "needs_loop": False,  "energy_score": round(energy_score, 3),
            }
        else:
            # Too short even after stretch — fall back to looping from start_sec
            return {
                "bpm": round(bpm, 1), "start_sec": round(start_sec, 3),
                "atempo": 1.0,        "trim_dur": None,
                "needs_loop": True,   "energy_score": round(energy_score, 3),
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
        print(f"  🎵 {name}")
        print(f"     {bpm_str} · {start_str} · {fit_str} · {energy_str}")
        results.append({"file": name, **info})

    return results

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


# ── שלב 1: חיתוך קליפ בודד ────────────────────────────────────────────────

def cut_clip(video_path: str, event: dict, index: int, slowmo: bool = False) -> str | None:
    """
    חותך רגע שיא:
    - 9:16 עם רקע מטושטש
    - slow-mo 50% אם slowmo=True (מקור ≥ 50fps)
    - color grade + fade
    - ללא אודיו
    """
    start, end = _clamp(event["start"], event["end"], video_path)
    input_dur  = end - start
    event_type = event.get("type", "highlight")

    if (event["start"], event["end"]) != (start, end):
        logger.warning("⚠️ Timestamps clamped [%.1f,%.1f]→[%.1f,%.1f]",
                       event["start"], event["end"], start, end)

    # משך הפלט: כפול אם slow-mo (FFmpeg קורא input_dur מהמקור, setpts מכפיל)
    output_dur = input_dur * 2 if slowmo else input_dur
    clip_fade  = min(CLIP_FADE_DUR, output_dur / 6)

    os.makedirs(config.TMP_DIR, exist_ok=True)
    out = os.path.join(config.TMP_DIR, f"{Path(video_path).stem}_clip{index:02d}.mp4")

    slowmo_filter = "setpts=2.0*PTS," if slowmo else ""

    vf = (
        f"[0:v]split[bg_in][fg_in];"

        # רקע מטושטש
        f"[bg_in]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
        f"crop={REEL_W}:{REEL_H},gblur=sigma=25:steps=2[bg];"

        # תמונה חדה
        f"[fg_in]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease[fg];"

        # overlay → slow-mo (אם פעיל) → grade → fade
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"{slowmo_filter}"
        f"eq=contrast=1.12:saturation=1.22:brightness=0.02,"
        f"unsharp=5:5:0.65,"
        f"fade=t=in:st=0:d={clip_fade:.2f},"
        f"fade=t=out:st={output_dur - clip_fade:.2f}:d={clip_fade:.2f}"
        f"[out]"
    )

    slowmo_tag = " [🐢 slow-mo]" if slowmo else ""
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

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            logger.error("FFmpeg clip %d: %s", index, r.stderr[-1500:])
            print(f"❌ Clip {index} failed: {r.stderr[-300:]}")
            return None
        return out
    except subprocess.TimeoutExpired:
        print(f"❌ Clip {index} timed out")
        return None
    except FileNotFoundError:
        print("❌ FFmpeg not found — install: sudo apt install ffmpeg")
        return None
    except Exception as e:
        logger.error("Clip %d unexpected: %s", index, e)
        return None


# ── שלב 2: compilation לריל אחד ──────────────────────────────────────────

def _xfade_filter(n: int, durations: list[float]) -> str:
    """בונה filter_complex ל-xfade crossfade בין n קליפים."""
    if n == 1:
        return "[0:v]null[xfout]"

    parts      = []
    offset     = round(durations[0] - XFADE_DUR, 3)
    out_lbl    = "[xfout]" if n == 2 else "[xf1]"
    parts.append(
        f"[0:v][1:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}{out_lbl}"
    )

    cumulative = durations[0] + durations[1] - XFADE_DUR
    for i in range(2, n):
        offset  = round(cumulative - XFADE_DUR, 3)
        prev    = "[xf1]" if i == 2 else f"[xf{i-1}]"
        out_lbl = "[xfout]" if i == n - 1 else f"[xf{i}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}{out_lbl}"
        )
        cumulative += durations[i] - XFADE_DUR

    return ";".join(parts)


def compile_reel(clip_paths: list[str], logo_path: str, output_path: str) -> str | None:
    """מחבר קליפים לריל אחד עם xfade + לוגו watermark."""
    n = len(clip_paths)
    if n == 0:
        return None

    durations = [_get_duration(p) for p in clip_paths]
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

    xfade_f = _xfade_filter(n, durations)

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

    music_path = _pick_music()
    has_music  = bool(music_path)
    music_idx  = n + (1 if has_logo else 0)
    if has_music:
        mx      = _analyze_music(music_path, total_dur)
        fade_st = max(0.0, total_dur - 2.0)

        if mx["needs_loop"]:
            # שיר קצר מדי — loop מנקודת ה-drop
            audio_f = (
                f"atrim=start={mx['start_sec']:.3f},"
                f"aloop=loop=-1:size=2000000000,"
                f"atrim=duration={total_dur:.3f},"
                f"afade=t=out:st={fade_st:.3f}:d=2"
            )
        elif abs(mx["atempo"] - 1.0) > 0.005:
            # stretch קל (±10%) כדי להתאים בדיוק לריל
            audio_f = (
                f"atrim=start={mx['start_sec']:.3f}:duration={mx['trim_dur']:.3f},"
                f"atempo={mx['atempo']:.4f},"
                f"afade=t=out:st={fade_st:.3f}:d=2"
            )
        else:
            # trim מדויק ממקום ה-drop — ללא stretch
            audio_f = (
                f"atrim=start={mx['start_sec']:.3f}:duration={total_dur:.3f},"
                f"afade=t=out:st={fade_st:.3f}:d=2"
            )

        inputs += ["-i", music_path]
        filter_complex += f";[{music_idx}:a]{audio_f}[aout]"

        bpm_str   = f"{mx['bpm']:.0f}bpm" if mx["bpm"] else "?"
        fit_label = ("loop" if mx["needs_loop"]
                     else f"×{mx['atempo']:.3f}" if abs(mx["atempo"] - 1.0) > 0.005
                     else "exact")
        print(f"🎵 {Path(music_path).name} — {bpm_str}, drop@{mx['start_sec']:.1f}s, {fit_label}")

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


# ── ממשק ראשי ─────────────────────────────────────────────────────────────

def create_reel(video_path: str, events: list[dict], sport: str = "") -> str | None:
    """
    מקבל סרטון גולמי + events מ-Gemini.
    מחזיר ריל 9:16 מוכן להעלאה.
    """
    print(f"\n🎬 Creating reel from '{Path(video_path).name}' ({len(events)} event(s))")

    # 1. סדר נרטיבי
    ordered = _narrative_order(events)
    order_log = " → ".join(f"{e['type']}({e['score']})" for e in ordered)
    print(f"📋 Narrative order: {order_log}")

    # 2. בדיקת fps לslow-mo
    source_fps = _get_source_fps(video_path)
    slowmo     = source_fps >= SLOWMO_FPS_MIN
    if slowmo:
        print(f"🐢 Source {source_fps:.0f}fps — slow-mo 50% enabled")
    else:
        print(f"⚡ Source {source_fps:.0f}fps — slow-mo skipped (need {SLOWMO_FPS_MIN}+fps)")

    # 3. חיתוך קליפים לפי הסדר הנרטיבי
    clip_paths: list[str] = []
    for i, event in enumerate(ordered, start=1):
        clip = cut_clip(video_path, event, i, slowmo=slowmo)
        if clip:
            clip_paths.append(clip)
        else:
            print(f"⚠️ Event {i} ({event.get('type')}) skipped")

    if not clip_paths:
        print("❌ No clips produced — cannot create reel")
        return None

    # 4. compilation לריל אחד
    sport_tag = f"_{sport}" if sport else ""
    reel_path = os.path.join(config.TMP_DIR, f"REEL_{Path(video_path).stem}{sport_tag}.mp4")
    reel      = compile_reel(clip_paths, config.LOGO_PATH, reel_path)

    for p in clip_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    return reel

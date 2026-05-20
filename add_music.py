"""
add_music.py — Beat-sync a song onto an existing no-music reel.

Usage:
    python add_music.py <reel_path> <song_path> [output_path]

Requires the clips cache produced by create_reel() / compile_multi_source_reel().
The meta.json lives at:
    <CLIPS_CACHE_DIR>/<reel_stem>/<reel_stem>.meta.json
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import config
from pipeline.editor import _analyze_music, compile_reel, _compute_cut_times

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SPEED_MIN = 0.85
_SPEED_MAX = 1.15


def _find_meta(reel_path: str) -> dict:
    reel_stem = Path(reel_path).stem
    candidates = [
        os.path.join(config.CLIPS_CACHE_DIR, reel_stem, f"{reel_stem}.meta.json"),
    ]
    for p in candidates:
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    raise FileNotFoundError(
        f"No clip cache found for '{reel_stem}'. "
        f"Looked in: {candidates[0]}"
    )


def _adjust_clip(clip_path: str, speed_factor: float, out_path: str) -> bool:
    """Re-time a clip by speed_factor using FFmpeg setpts (video) + atempo (audio-less)."""
    pts = f"{1.0 / speed_factor:.6f}"
    cmd = [
        "ffmpeg", "-y", "-i", clip_path,
        "-vf", f"setpts={pts}*PTS",
        "-an",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-r", "30",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        logger.warning("Speed-adjust failed for %s: %s",
                       Path(clip_path).name, r.stderr.decode(errors="replace")[-300:])
        return False
    return True


def _get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=15,
    )
    return float(r.stdout.strip() or 0)


def add_music(reel_path: str, song_path: str, output_path: str | None = None) -> str:
    meta = _find_meta(reel_path)
    clip_paths: list[str] = meta["clip_paths"]
    sport: str = meta.get("sport", "")
    athlete_label: str = meta.get("athlete_label", "")

    missing = [p for p in clip_paths if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"Cached clips missing ({len(missing)} file(s)):\n" +
            "\n".join(f"  {p}" for p in missing[:5])
        )

    durations = [_get_duration(p) for p in clip_paths]
    total_dur = sum(durations)
    cut_times = _compute_cut_times(durations) or None

    mx = _analyze_music(song_path, total_dur, cut_times=cut_times)
    bpm: float = mx["bpm"] or 0.0

    if not bpm:
        logger.warning("BPM detection failed — using original clip durations")
        beat_dur = None
    else:
        beat_dur = 60.0 / bpm
        print(f"🎵 Song: {Path(song_path).name} — {bpm:.0f} BPM (beat={beat_dur:.3f}s)")

    tmp_dir = tempfile.mkdtemp(prefix="add_music_")
    adjusted: list[str] = []

    try:
        for i, (clip_p, d_i) in enumerate(zip(clip_paths, durations)):
            if beat_dur and d_i > 0:
                k = max(1, round(d_i / beat_dur))
                t_i = k * beat_dur
                f_i = d_i / t_i
            else:
                f_i = 1.0

            if abs(f_i - 1.0) < 0.001 or not (_SPEED_MIN <= f_i <= _SPEED_MAX):
                if not (_SPEED_MIN <= f_i <= _SPEED_MAX) and beat_dur:
                    logger.warning(
                        "Clip %d: speed factor %.3f outside [%.2f,%.2f] — using original",
                        i, f_i, _SPEED_MIN, _SPEED_MAX,
                    )
                adjusted.append(clip_p)
            else:
                adj_path = os.path.join(tmp_dir, f"adj_{i:02d}.mp4")
                if _adjust_clip(clip_p, f_i, adj_path):
                    adjusted.append(adj_path)
                    print(f"  Clip {i}: {d_i:.3f}s → {t_i:.3f}s (×{f_i:.3f})")
                else:
                    adjusted.append(clip_p)

        if output_path is None:
            stem = Path(reel_path).stem
            output_path = str(Path(reel_path).parent / f"{stem}_music.mp4")

        result = compile_reel(
            adjusted,
            config.LOGO_PATH,
            output_path,
            sport=sport,
            athlete_label=athlete_label,
            music_path=song_path,
        )

        if result:
            print(f"\n✅ Music reel ready: {result}")
        else:
            print("\n❌ compile_reel failed")
            sys.exit(1)

    finally:
        for p in adjusted:
            if p.startswith(tmp_dir):
                try:
                    os.remove(p)
                except OSError:
                    pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python add_music.py <reel_path> <song_path> [output_path]")
        sys.exit(1)

    _reel   = sys.argv[1]
    _song   = sys.argv[2]
    _output = sys.argv[3] if len(sys.argv) > 3 else None

    add_music(_reel, _song, _output)

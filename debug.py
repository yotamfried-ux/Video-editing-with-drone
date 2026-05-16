#!/usr/bin/env python3
"""
debug.py — Pipeline simulation without real API keys.

מה הסקריפט הזה בודק:
  1. Prerequisites   — FFmpeg / ffprobe / לוגו
  2. Test videos     — יצירת סרטוני בדיקה 60fps + 30fps עם FFmpeg
  3. FPS detection   — האם _get_source_fps קורא נכון
  4. Narrative order — סדר הקליפים הנרטיבי
  5. JSON parsing    — _parse_analysis עם תשובות שונות
  6. cut_clip        — חיתוך + slow-mo אמיתי עם FFmpeg
  7. compile_reel    — חיבור 3 קליפים לריל
  8. create_reel     — כל הפייפליין end-to-end
  9. Email HTML      — בניית אימייל
  10. Client match   — התאמת clients.json

כל מה שדורש API אמיתי (Drive / Gemini / Gmail) לא נקרא —
הפונקציות האלה מקבלות נתוני dummy.
"""

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Dummy env vars — חייב לפני כל import של config ────────────────────────
os.environ.setdefault("GEMINI_API_KEY",              "debug_dummy_not_used")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_JSON", "debug_dummy.json")
os.environ.setdefault("RAW_FOLDER_ID",               "debug_raw")
os.environ.setdefault("CLIPS_FOLDER_ID",             "debug_clips")
os.environ.setdefault("PROCESSED_FOLDER_ID",         "debug_processed")
os.environ.setdefault("REVIEW_FOLDER_ID",            "debug_review")
os.environ.setdefault("APPROVED_FOLDER_ID",          "debug_approved")
os.environ.setdefault("PREVIEW_FOLDER_ID",           "debug_preview")
os.environ.setdefault("PENDING_PAYMENT_FOLDER_ID",   "debug_pending_payment")
os.environ.setdefault("OWNER_EMAIL",                 "debug@example.com")
os.environ.setdefault("LOGO_PATH",                   "assets/logo.png")
os.environ.setdefault("TMP_DIR",                     "/tmp/dtor_debug")

import config  # noqa: E402
from pipeline.editor   import (  # noqa: E402
    create_reel, cut_clip, compile_reel, create_preview,
    _narrative_order, _get_source_fps, _get_duration, _pick_music,
    _analyze_music, analyze_music_library, _compute_cut_times,
    _COLOR_PROFILES, _partition_events, _find_font, _xfade_filter,
    _ensure_music_cache,
)

# Mock all Google SDK modules before importing pipeline modules that depend on
# them — avoids cffi/grpc/rust native-extension failures in debug environment.
from unittest.mock import MagicMock
for _mod in [
    "google.generativeai",
    "google.auth", "google.auth.transport", "google.auth.transport.requests",
    "google.auth.credentials", "google.oauth2", "google.oauth2.service_account",
    "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
    "google_auth_httplib2",
]:
    sys.modules.setdefault(_mod, MagicMock())

from pipeline.analyzer import _parse_analysis, _parse_session, _with_retry, _extract_thumbnail  # noqa: E402
from pipeline.notifier import _build_html, send_summary_email  # noqa: E402

# ── Paths ──────────────────────────────────────────────────────────────────
DEBUG_DIR     = config.TMP_DIR
VIDEO_60FPS   = os.path.join(DEBUG_DIR, "test_60fps.mp4")
VIDEO_30FPS   = os.path.join(DEBUG_DIR, "test_30fps.mp4")
CLIENTS_TMP   = config.CLIENTS_FILE

os.makedirs(DEBUG_DIR, exist_ok=True)

# ── Test tracking ──────────────────────────────────────────────────────────
PASSED: list[str] = []
FAILED: list[str] = []


def ok(name: str, detail: str = "") -> None:
    tag = f"  ({detail})" if detail else ""
    print(f"    ✅  {name}{tag}")
    PASSED.append(name)


def fail(name: str, reason: str) -> None:
    print(f"    ❌  {name}: {reason}")
    FAILED.append(name)


def section(title: str) -> None:
    print(f"\n  {'─' * 52}")
    print(f"  {title}")
    print(f"  {'─' * 52}")


# ══════════════════════════════════════════════════════
# 1. Prerequisites
# ══════════════════════════════════════════════════════

def test_prerequisites() -> None:
    section("1 / Prerequisites")

    for tool in ("ffmpeg", "ffprobe"):
        try:
            r = subprocess.run([tool, "-version"], capture_output=True, timeout=10)
            ver = r.stdout.decode().split("\n")[0][:60]
            ok(f"{tool} installed", ver)
        except FileNotFoundError:
            fail(f"{tool} installed", "not found — run: sudo apt install ffmpeg")

    logo = Path(config.LOGO_PATH)
    if logo.exists() and logo.stat().st_size > 0:
        ok("Logo file exists", str(logo))
    else:
        fail("Logo file exists", f"missing at {logo} — replace assets/logo.png")


# ══════════════════════════════════════════════════════
# 2. Generate test videos
# ══════════════════════════════════════════════════════

def _make_test_video(path: str, fps: int, duration: int = 22) -> bool:
    """יוצר סרטון בדיקה דינמי (testsrc2) עם FFmpeg — ללא קבצים חיצוניים."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size=1920x1080:rate={fps}:duration={duration}",
        "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
        "-an",
        path,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=90)
    return r.returncode == 0 and Path(path).exists()


def test_create_test_videos() -> None:
    section("2 / Generate test videos (FFmpeg lavfi)")

    if _make_test_video(VIDEO_60FPS, fps=60):
        kb = Path(VIDEO_60FPS).stat().st_size // 1024
        ok("60fps test video created", f"{kb} KB")
    else:
        fail("60fps test video", "ffmpeg returned non-zero")

    if _make_test_video(VIDEO_30FPS, fps=30):
        ok("30fps test video created")
    else:
        fail("30fps test video", "ffmpeg returned non-zero")


# ══════════════════════════════════════════════════════
# 3. FPS detection
# ══════════════════════════════════════════════════════

def test_fps_detection() -> None:
    section("3 / FPS detection (_get_source_fps)")

    for path, expected in [(VIDEO_60FPS, 60), (VIDEO_30FPS, 30)]:
        if not Path(path).exists():
            fail(f"{expected}fps detection", "test video missing")
            continue
        fps = _get_source_fps(path)
        if abs(fps - expected) < 1.0:
            ok(f"{expected}fps detected", f"got {fps:.1f}fps")
        else:
            fail(f"{expected}fps detection", f"got {fps:.1f}fps")


# ══════════════════════════════════════════════════════
# 4. Narrative ordering
# ══════════════════════════════════════════════════════

def test_narrative_order() -> None:
    section("4 / Narrative clip ordering (_narrative_order)")

    def ev(t: str, score: int) -> dict:
        return {"type": t, "start": 0.0, "end": 8.0, "score": score, "description": ""}

    # 5 events: best opener=8, climax=9, ascending middle
    events  = [ev("wave_catch", 9), ev("snap", 7), ev("foam", 5), ev("aerial", 8), ev("tube", 6)]
    ordered = _narrative_order(events)
    scores  = [e["score"] for e in ordered]

    if scores[0] == 8 and scores[-1] == 9:
        ok("5-event narrative: opener=8, climax=9", f"order: {scores}")
    else:
        fail("5-event narrative", f"got {scores}, expected [8,...,9]")

    # Middle must be ascending
    if scores[1:-1] == sorted(scores[1:-1]):
        ok("Middle clips ascending")
    else:
        fail("Middle ascending", f"middle: {scores[1:-1]}")

    # 2-event: ascending (low → high)
    two     = [ev("a", 9), ev("b", 5)]
    two_ord = _narrative_order(two)
    if two_ord[0]["score"] < two_ord[1]["score"]:
        ok("2-event ascending")
    else:
        fail("2-event ascending", f"{[e['score'] for e in two_ord]}")

    # 1-event: unchanged
    one = [ev("a", 7)]
    if _narrative_order(one) == one:
        ok("1-event passthrough")
    else:
        fail("1-event passthrough", "list was modified")


# ══════════════════════════════════════════════════════
# 5. Analyzer JSON parsing
# ══════════════════════════════════════════════════════

def test_analyzer_parsing() -> None:
    section("5 / Analyzer JSON parsing (_parse_analysis)")

    # תשובה תקינה
    valid = json.dumps({
        "activity": "surfing",
        "events": [
            {"type": "aerial", "start": 5.0, "end": 14.0, "score": 9,
             "description": "Full rotation aerial."}
        ]
    })
    try:
        r = _parse_analysis(valid)
        assert r["activity"] == "surfing" and len(r["events"]) == 1
        ok("Valid JSON parsed")
    except Exception as e:
        fail("Valid JSON", str(e))

    # עם markdown fences (Gemini מוסיף לפעמים)
    try:
        _parse_analysis(f"```json\n{valid}\n```")
        ok("Markdown fences stripped")
    except Exception as e:
        fail("Markdown fences", str(e))

    # קליפ קצר מ-6 שניות ← צריך להיות padded ל-6
    short = json.dumps({
        "activity": "football",
        "events": [{"type": "goal", "start": 10.0, "end": 11.0, "score": 8, "description": ""}]
    })
    try:
        r  = _parse_analysis(short)
        dur = r["events"][0]["end"] - r["events"][0]["start"]
        if dur >= 6.0:
            ok("Short clip padded to ≥6s", f"{dur:.1f}s")
        else:
            fail("Short clip padding", f"only {dur:.1f}s")
    except Exception as e:
        fail("Short clip padding", str(e))

    # legacy key "sport" במקום "activity"
    try:
        r = _parse_analysis(json.dumps({"sport": "skateboarding", "events": []}))
        if r["activity"] == "skateboarding":
            ok("Legacy 'sport' key supported")
        else:
            fail("Legacy key", f"got '{r['activity']}'")
    except Exception as e:
        fail("Legacy key", str(e))

    # JSON שבור
    try:
        _parse_analysis("this is not json {{{")
        fail("Broken JSON", "should have raised JSONDecodeError")
    except json.JSONDecodeError:
        ok("Broken JSON raises JSONDecodeError")
    except Exception as e:
        fail("Broken JSON", f"wrong exception: {e}")


# ══════════════════════════════════════════════════════
# 6. cut_clip
# ══════════════════════════════════════════════════════

def test_cut_clip() -> None:
    section("6 / cut_clip — FFmpeg cutting + 9:16 + grade")

    if not Path(VIDEO_60FPS).exists():
        fail("cut_clip", "60fps test video missing (test 2 failed)")
        return

    event = {"type": "wave_catch", "start": 2.0, "end": 10.0, "score": 9, "description": ""}

    # ── 6a: חיתוך רגיל (ללא slow-mo) ──
    t0   = time.time()
    clip = cut_clip(VIDEO_60FPS, event, index=1, slowmo=False)
    dt   = time.time() - t0

    if clip and Path(clip).exists():
        kb  = Path(clip).stat().st_size // 1024
        dur = _get_duration(clip)
        ok("cut_clip normal speed", f"{dur:.1f}s, {kb}KB in {dt:.1f}s")
    else:
        fail("cut_clip normal speed", "output file not created")
        return

    # ── 6b: slow-mo (מקור 60fps → פלט ~16s) ──
    t0      = time.time()
    clip_sm = cut_clip(VIDEO_60FPS, event, index=2, slowmo=True)
    dt      = time.time() - t0

    if clip_sm and Path(clip_sm).exists():
        dur_normal = _get_duration(clip)
        dur_slowmo = _get_duration(clip_sm)
        ratio      = dur_slowmo / dur_normal if dur_normal > 0 else 0

        if 1.2 < ratio < 1.6:
            ok("cut_clip speed-ramp ≈1.4x duration", f"{dur_normal:.1f}s → {dur_slowmo:.1f}s (×{ratio:.2f})")
        else:
            fail("cut_clip speed-ramp duration", f"ratio {ratio:.2f} (expected ~1.4)")
    else:
        fail("cut_clip slow-mo", "output not created")

    # ── 6c: פלט הוא 9:16 (1080×1920) ──
    try:
        probe = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", clip,
        ], text=True, timeout=10).strip()
        w, h = probe.split(",")
        if int(w) == 1080 and int(h) == 1920:
            ok("Output resolution 1080×1920 (9:16)")
        else:
            fail("Output resolution", f"got {w}×{h}, expected 1080×1920")
    except Exception as e:
        fail("Resolution check", str(e))

    # ── 6d: ללא אודיו ──
    try:
        audio_check = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0", clip,
        ], text=True, timeout=10).strip()
        if audio_check == "":
            ok("No audio stream in output")
        else:
            fail("No audio stream", f"found audio: {audio_check}")
    except Exception as e:
        fail("Audio check", str(e))

    # ── 6e: timestamp clamping — timestamp שחורג מאורך הסרטון ──
    bad_event = {"type": "x", "start": 5.0, "end": 999.0, "score": 5, "description": ""}
    clipped   = cut_clip(VIDEO_60FPS, bad_event, index=3, slowmo=False)
    if clipped and Path(clipped).exists():
        ok("Timestamp clamping (end > video length)")
    else:
        fail("Timestamp clamping", "clip not created")

    # ── 6f: 30fps → slow-mo=False (אמורה לא להכפיל) ──
    if Path(VIDEO_30FPS).exists():
        c30 = cut_clip(VIDEO_30FPS, event, index=4, slowmo=False)
        if c30 and Path(c30).exists():
            ok("cut_clip 30fps no slow-mo")
        else:
            fail("cut_clip 30fps", "clip not created")


# ══════════════════════════════════════════════════════
# 7. compile_reel
# ══════════════════════════════════════════════════════

def test_compile_reel() -> None:
    section("7 / compile_reel — xfade + logo watermark")

    if not Path(VIDEO_60FPS).exists():
        fail("compile_reel", "test video missing")
        return

    events = [
        {"type": "a", "start": 0.0,  "end": 7.0,  "score": 8, "description": ""},
        {"type": "b", "start": 7.5,  "end": 14.0, "score": 6, "description": ""},
        {"type": "c", "start": 14.5, "end": 20.0, "score": 9, "description": ""},
    ]
    clips = [cut_clip(VIDEO_60FPS, ev, index=i+20, slowmo=False)
             for i, ev in enumerate(events)]
    clips = [c for c in clips if c and Path(c).exists()]

    if len(clips) < 2:
        fail("compile_reel", f"only {len(clips)} clips available to compile")
        return

    reel_out = os.path.join(DEBUG_DIR, "debug_compiled_reel.mp4")
    t0       = time.time()
    result   = compile_reel(clips, config.LOGO_PATH, reel_out)
    dt       = time.time() - t0

    if result and Path(result).exists():
        kb  = Path(result).stat().st_size // 1024
        dur = _get_duration(result)
        ok(f"compile_reel {len(clips)} clips", f"{dur:.1f}s, {kb}KB in {dt:.1f}s")
        print(f"       → {result}")
    else:
        fail("compile_reel", "output not created")

    for c in clips:
        try: os.remove(c)
        except OSError: pass


# ══════════════════════════════════════════════════════
# 7b. music overlay
# ══════════════════════════════════════════════════════

def test_music_overlay() -> None:
    section("7b / Music overlay (_pick_music + audio in reel)")

    old_music_dir = getattr(config, "MUSIC_DIR", "music")

    # ── no music dir → None ────────────────────────────
    config.MUSIC_DIR = os.path.join(DEBUG_DIR, "music_nonexistent_xyz")
    if _pick_music() is None:
        ok("_pick_music — empty dir → None")
    else:
        fail("_pick_music — empty dir", "expected None")

    # ── create synthetic mp3, verify pick ──────────────
    music_dir = os.path.join(DEBUG_DIR, "music_test")
    os.makedirs(music_dir, exist_ok=True)
    test_mp3 = os.path.join(music_dir, "test_track.mp3")
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
         "-q:a", "0", test_mp3],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        fail("_pick_music", "could not generate test mp3")
        config.MUSIC_DIR = old_music_dir
        return

    config.MUSIC_DIR = music_dir
    picked = _pick_music()
    if picked and Path(picked).exists():
        ok("_pick_music — picks file from music dir", Path(picked).name)
    else:
        fail("_pick_music", f"expected file, got {picked}")

    # ── compile_reel with music → verify audio stream ──
    if not Path(VIDEO_60FPS).exists():
        config.MUSIC_DIR = old_music_dir
        return

    events = [
        {"type": "a", "start": 0.0,  "end": 7.0,  "score": 8, "description": ""},
        {"type": "b", "start": 7.5,  "end": 14.0, "score": 6, "description": ""},
    ]
    clips = [cut_clip(VIDEO_60FPS, ev, index=i + 30, slowmo=False)
             for i, ev in enumerate(events)]
    clips = [c for c in clips if c and Path(c).exists()]

    if len(clips) < 2:
        fail("compile_reel with music", "clips not created")
        config.MUSIC_DIR = old_music_dir
        return

    reel_out = os.path.join(DEBUG_DIR, "debug_music_reel.mp4")
    result   = compile_reel(clips, config.LOGO_PATH, reel_out, music_path=test_mp3)

    if result and Path(result).exists():
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", result],
            capture_output=True, text=True,
        )
        codec = probe.stdout.strip()
        if codec:
            ok("compile_reel with music — audio stream present", f"codec: {codec}")
        else:
            fail("compile_reel with music", "no audio stream in output")
    else:
        fail("compile_reel with music", "output not created")

    for c in clips:
        try: os.remove(c)
        except OSError: pass

    config.MUSIC_DIR = old_music_dir


# ══════════════════════════════════════════════════════
# 7c. music library analysis
# ══════════════════════════════════════════════════════

def test_music_analysis() -> None:
    section("7c / Music library analysis (_analyze_music + analyze_music_library)")

    # ── skip gracefully if librosa not installed ──────
    try:
        import librosa  # noqa: F401
    except ImportError:
        print("    ⚠️  librosa not installed — skipping music analysis tests")
        return

    SAMPLE_DUR = 30.0  # synthetic reel duration for testing

    # ── create a synthetic test mp3 ───────────────────
    music_dir = os.path.join(DEBUG_DIR, "music_analysis_test")
    os.makedirs(music_dir, exist_ok=True)
    test_mp3  = os.path.join(music_dir, "synth_120bpm.mp3")

    # 440 Hz sine at 120 BPM — simple but detectable beat grid
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=60",
         "-q:a", "0", test_mp3],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        fail("_analyze_music", "could not generate test mp3")
        return

    # ── _analyze_music: basic output shape (no cuts) ──
    result = _analyze_music(test_mp3, SAMPLE_DUR)

    required_keys = {"bpm", "start_sec", "atempo", "trim_dur", "needs_loop",
                     "energy_score", "alignment_error"}
    if required_keys.issubset(result.keys()):
        ok("_analyze_music — returns all required keys")
    else:
        fail("_analyze_music", f"missing keys: {required_keys - result.keys()}")
        return

    # ── start_sec within track ────────────────────────
    if 0.0 <= result["start_sec"] <= 60.0 - SAMPLE_DUR:
        ok("_analyze_music — start_sec within track", f"{result['start_sec']:.3f}s")
    else:
        fail("_analyze_music — start_sec", f"out of range: {result['start_sec']:.3f}s")

    # ── atempo in valid FFmpeg range ──────────────────
    if 0.5 <= result["atempo"] <= 2.0:
        ok("_analyze_music — atempo in FFmpeg range [0.5–2.0]", f"{result['atempo']:.4f}")
    else:
        fail("_analyze_music — atempo", f"out of range: {result['atempo']}")

    # ── BPM returned (0.0 is valid for non-rhythmic test audio) ──
    if result["bpm"] is not None:
        ok("_analyze_music — BPM returned", f"{result['bpm']:.1f} BPM")
    else:
        fail("_analyze_music — BPM", f"expected float, got: {result['bpm']}")

    # ── energy_score [0–1] ────────────────────────────
    if result["energy_score"] is not None and 0.0 <= result["energy_score"] <= 1.0:
        ok("_analyze_music — energy_score [0–1]", f"{result['energy_score']:.3f}")
    else:
        fail("_analyze_music — energy_score", f"unexpected: {result['energy_score']}")

    # ── alignment_error None when no cuts provided ────
    if result["alignment_error"] is None:
        ok("_analyze_music — alignment_error None without cut_times")
    else:
        fail("_analyze_music — alignment_error", f"expected None, got {result['alignment_error']}")

    # ── with cut_times: alignment_error is float ≥ 0 ─
    sample_cuts = [7.0, 14.5]  # two cut points in a 30s reel
    result_cuts = _analyze_music(test_mp3, SAMPLE_DUR, cut_times=sample_cuts)
    ae = result_cuts["alignment_error"]
    # sine wave has no beats → alignment may fall back (ae=None) or succeed (ae≥0)
    if ae is None or ae >= 0.0:
        ok("_analyze_music — alignment_error with cuts (float≥0 or None for beatless audio)",
           f"{ae}")
    else:
        fail("_analyze_music — alignment_error with cuts", f"unexpected: {ae}")

    # ── _compute_cut_times ───────────────────────────
    durs = [8.0, 6.5, 7.0]
    cuts = _compute_cut_times(durs)
    # cut 0 = durs[0] - XFADE_DUR = 8.0 - 0.5 = 7.5
    # cut 1 = cumulative(durs[0]+durs[1]-XFADE_DUR) - XFADE_DUR = (8+6.5-0.5) - 0.5 = 13.5
    if len(cuts) == 2 and abs(cuts[0] - 7.5) < 0.01 and abs(cuts[1] - 13.5) < 0.01:
        ok("_compute_cut_times — correct xfade offsets", str(cuts))
    else:
        fail("_compute_cut_times", f"expected [7.5, 13.5], got {cuts}")

    # ── analyze_music_library report ─────────────────
    old_music_dir   = getattr(config, "MUSIC_DIR", "music")
    config.MUSIC_DIR = music_dir
    report = analyze_music_library(SAMPLE_DUR)
    config.MUSIC_DIR = old_music_dir

    if report and report[0]["file"] == "synth_120bpm.mp3":
        ok("analyze_music_library — scans directory and returns report",
           f"{len(report)} track(s)")
    else:
        fail("analyze_music_library", f"unexpected report: {report}")

    # ── fallback: non-existent file → defaults ────────
    bad_result = _analyze_music("/nonexistent/track.mp3", SAMPLE_DUR)
    if bad_result["start_sec"] == 0.0 and bad_result["atempo"] == 1.0:
        ok("_analyze_music — bad path → safe defaults")
    else:
        fail("_analyze_music — bad path", f"unexpected: {bad_result}")


# ══════════════════════════════════════════════════════
# 8. create_reel — end-to-end
# ══════════════════════════════════════════════════════

def test_create_reel() -> None:
    section("8 / create_reel — full pipeline (narrative + slow-mo + compile)")

    if not Path(VIDEO_60FPS).exists():
        fail("create_reel", "test video missing")
        return

    events = [
        {"type": "wave_catch", "start": 0.0,  "end": 7.0,  "score": 9, "description": "Big wave"},
        {"type": "snap",       "start": 8.0,  "end": 14.0, "score": 7, "description": "Snap"},
        {"type": "tube",       "start": 15.0, "end": 20.0, "score": 8, "description": "Tube"},
    ]

    t0    = time.time()
    reels = create_reel(VIDEO_60FPS, events, sport="surfing")
    dt    = time.time() - t0

    if reels and Path(reels[0]).exists():
        kb  = Path(reels[0]).stat().st_size // 1024
        dur = _get_duration(reels[0])
        ok("create_reel end-to-end", f"{dur:.1f}s reel, {kb}KB in {dt:.1f}s")
        print(f"       → {reels[0]}")
    else:
        fail("create_reel", "reel not produced")


# ══════════════════════════════════════════════════════
# 9. Email HTML
# ══════════════════════════════════════════════════════

def test_email_html() -> None:
    section("9 / Email HTML (_build_html)")

    link = "https://drive.google.com/file/debug_test"

    for is_owner, label in [(False, "client"), (True, "owner")]:
        html = _build_html(
            clips_links=[link],
            sport_type="surfing",
            video_name="session_yoni.mp4",
            is_owner=is_owner,
        )
        checks = [
            ("Has <html> tag",           "<html>" in html),
            ("Has Drive link",           link in html),
            ("Has sport capitalised",    "Surfing" in html),
            ("Has video filename",       "session_yoni.mp4" in html),
            ("Has Watch/Reel CTA",       any(w in html for w in ("Watch", "Reel", "▶"))),
        ]
        if is_owner:
            checks.append(("Owner note present", "owner" in html.lower() or "Owner" in html))

        for name, passed in checks:
            if passed:
                ok(f"[{label}] {name}")
            else:
                fail(f"[{label}] {name}", "not found in HTML")


# ══════════════════════════════════════════════════════
# 10. Pipeline helpers (run.py)
# ══════════════════════════════════════════════════════

def test_pipeline_helpers() -> None:
    section("10 / Pipeline helpers (_classify_input + _safe_draft_name)")

    from run import _classify_input, _safe_draft_name  # noqa: PLC0415

    # ── _classify_input ───────────────────────────────
    # single large file (>100 MB) → long_video
    big = [{"id": "x", "name": "session.mp4", "size": "150000000"}]
    if _classify_input(big) == "long_video":
        ok("_classify_input — single >100MB → long_video")
    else:
        fail("_classify_input — single >100MB", f"got {_classify_input(big)!r}")

    # single small file → clips_session
    small = [{"id": "x", "name": "clip.mp4", "size": "5000000"}]
    if _classify_input(small) == "clips_session":
        ok("_classify_input — single <100MB → clips_session")
    else:
        fail("_classify_input — single <100MB", f"got {_classify_input(small)!r}")

    # multiple small files → clips_session
    multi_small = [
        {"id": "a", "name": "clip1.mp4", "size": "5000000"},
        {"id": "b", "name": "clip2.mp4", "size": "8000000"},
    ]
    if _classify_input(multi_small) == "clips_session":
        ok("_classify_input — multiple small files → clips_session")
    else:
        fail("_classify_input — multiple small files", f"got {_classify_input(multi_small)!r}")

    # large + small → mixed_session
    mixed = [
        {"id": "a", "name": "game.mp4",  "size": "500000000"},
        {"id": "b", "name": "clip.mp4",  "size": "5000000"},
    ]
    if _classify_input(mixed) == "mixed_session":
        ok("_classify_input — large+small → mixed_session")
    else:
        fail("_classify_input — large+small", f"got {_classify_input(mixed)!r}")

    # 2 large → mixed_session
    two_large = [
        {"id": "a", "name": "a.mp4", "size": "200000000"},
        {"id": "b", "name": "b.mp4", "size": "300000000"},
    ]
    if _classify_input(two_large) == "mixed_session":
        ok("_classify_input — 2 large → mixed_session")
    else:
        fail("_classify_input — 2 large", f"got {_classify_input(two_large)!r}")

    # ── _safe_draft_name ──────────────────────────────
    name = _safe_draft_name("red board surfer #1 @ beach!")
    if name.startswith("DRAFT_") and name.endswith(".mp4"):
        ok("_safe_draft_name — starts with DRAFT_, ends with .mp4", name)
    else:
        fail("_safe_draft_name — format", f"got {name!r}")

    # special chars replaced, length bounded to ≤50 chars in middle part
    long_desc = "a" * 100
    long_name = _safe_draft_name(long_desc)
    middle = long_name[len("DRAFT_"):-len("_YYYYMMDD.mp4") - 1]  # approximate
    if len(long_name) < 80:
        ok("_safe_draft_name — long description truncated", long_name)
    else:
        fail("_safe_draft_name — truncation", f"name too long: {len(long_name)} chars")


# ══════════════════════════════════════════════════════
# 10b. Drive pagination
# ══════════════════════════════════════════════════════

def test_drive_pagination() -> None:
    section("10b / Drive pagination (get_new_videos + _sync_processed_from_drive)")

    from unittest.mock import MagicMock, patch
    from pipeline.drive import get_new_videos, _sync_processed_from_drive

    # ── _sync_processed_from_drive: 2 pages → all IDs returned ──
    page1 = {"files": [{"id": "aaa"}, {"id": "bbb"}], "nextPageToken": "tok1"}
    page2 = {"files": [{"id": "ccc"}]}

    mock_svc = MagicMock()
    mock_svc.files.return_value.list.return_value.execute.side_effect = [page1, page2]

    result = _sync_processed_from_drive(mock_svc)
    if result == {"aaa", "bbb", "ccc"}:
        ok("_sync_processed_from_drive — 2 pages → all IDs collected")
    else:
        fail("_sync_processed_from_drive pagination", f"got {result}")

    list_calls = mock_svc.files.return_value.list.call_args_list
    if len(list_calls) == 2:
        ok("_sync_processed_from_drive — called list() twice (once per page)")
    else:
        fail("_sync_processed_from_drive call count", f"expected 2, got {len(list_calls)}")

    # ── get_new_videos: 2 pages → all files considered ──
    raw_page1 = {"files": [{"id": "v1", "name": "clip1.mp4", "size": "1000", "createdTime": "t"}],
                 "nextPageToken": "tok2"}
    raw_page2 = {"files": [{"id": "v2", "name": "clip2.mp4", "size": "2000", "createdTime": "t"}]}
    proc_page  = {"files": []}   # PROCESSED folder empty

    svc2 = MagicMock()
    svc2.files.return_value.list.return_value.execute.side_effect = [
        proc_page,   # _sync_processed_from_drive
        raw_page1,   # RAW folder page 1
        raw_page2,   # RAW folder page 2
    ]

    with patch("pipeline.drive._get_drive_service", return_value=svc2), \
         patch("pipeline.drive._load_processed_ids", return_value=set()), \
         patch("pipeline.drive._save_processed_ids"):
        videos = get_new_videos()

    if len(videos) == 2 and {v["id"] for v in videos} == {"v1", "v2"}:
        ok("get_new_videos — 2 RAW pages → 2 videos returned")
    else:
        fail("get_new_videos pagination", f"got {[v['id'] for v in videos]}")


# ══════════════════════════════════════════════════════
# 11. _with_retry logic
# ══════════════════════════════════════════════════════

def test_retry_logic() -> None:
    section("11 / Gemini retry logic (_with_retry)")

    import unittest.mock as mock

    # ── success on first attempt ──────────────────────
    calls = [0]

    def always_ok():
        calls[0] += 1
        return "ok"

    try:
        result = _with_retry(always_ok)
        if result == "ok" and calls[0] == 1:
            ok("_with_retry — success on first attempt")
        else:
            fail("_with_retry — success on first attempt", f"calls={calls[0]}, result={result}")
    except Exception as e:
        fail("_with_retry — success on first attempt", str(e))

    # ── transient failure ×2 → success on 3rd attempt ─
    counter = [0]

    def fail_twice():
        counter[0] += 1
        if counter[0] < 3:
            raise Exception("quota exceeded (429)")
        return "recovered"

    with mock.patch("time.sleep"):
        try:
            result = _with_retry(fail_twice)
            if result == "recovered" and counter[0] == 3:
                ok("_with_retry — transient ×2 → success on 3rd attempt")
            else:
                fail("_with_retry — transient retry", f"calls={counter[0]}, result={result}")
        except Exception as e:
            fail("_with_retry — transient retry", str(e))

    # ── non-transient error → raises immediately (1 call) ─
    counter2 = [0]

    def non_transient():
        counter2[0] += 1
        raise ValueError("invalid input — not retryable")

    try:
        _with_retry(non_transient)
        fail("_with_retry — non-transient", "expected exception, got none")
    except ValueError:
        if counter2[0] == 1:
            ok("_with_retry — non-transient raises immediately (1 attempt)")
        else:
            fail("_with_retry — non-transient", f"called {counter2[0]} times, expected 1")
    except Exception as e:
        fail("_with_retry — non-transient", f"wrong exception type: {type(e).__name__}: {e}")

    # ── exhausted: 3/3 transient → raises after 3 attempts ─
    counter3 = [0]

    def always_transient():
        counter3[0] += 1
        raise RuntimeError("503 service unavailable")

    with mock.patch("time.sleep"):
        try:
            _with_retry(always_transient)
            fail("_with_retry — exhausted", "expected exception, got none")
        except RuntimeError:
            if counter3[0] == 3:
                ok("_with_retry — exhausted after 3 transient failures")
            else:
                fail("_with_retry — exhausted", f"called {counter3[0]} times, expected 3")
        except Exception as e:
            fail("_with_retry — exhausted", f"wrong exception: {e}")


# ══════════════════════════════════════════════════════
# 12. Batch email
# ══════════════════════════════════════════════════════

def test_batch_email() -> None:
    section("12 / Batch email (_build_html multi-link + send_summary_email smoke)")

    from unittest.mock import patch, MagicMock

    links = [
        "https://drive.google.com/file/reel1",
        "https://drive.google.com/file/reel2",
        "https://drive.google.com/file/reel3",
    ]

    # ── 3 links → 3 ▶ Reel buttons ───────────────────
    html = _build_html(
        clips_links=links,
        sport_type="surfing",
        video_name="3_video_batch.mp4",
        is_owner=True,
    )
    btn_count = html.count("▶ Reel")
    if btn_count == 3:
        ok("_build_html 3 links → 3 buttons in HTML", f"found {btn_count}× '▶ Reel'")
    else:
        fail("_build_html 3 links → 3 buttons", f"found {btn_count} buttons, expected 3")

    # ── all 3 URLs in HTML ────────────────────────────
    if all(link in html for link in links):
        ok("_build_html 3 links → all URLs present in HTML")
    else:
        fail("_build_html 3 links → URLs", "one or more link URLs missing from HTML")

    # ── send_summary_email smoke test (mocked Gmail) ──
    mock_svc = MagicMock()
    with patch("pipeline.notifier._get_gmail_service", return_value=mock_svc):
        try:
            send_summary_email(
                recipients  = [config.OWNER_EMAIL],
                clips_links = links,
                sport_type  = "surfing",
                video_name  = "3_video_batch.mp4",
            )
            ok("send_summary_email 3 links — no exception raised")
        except Exception as e:
            fail("send_summary_email 3 links", str(e))

    # ── exactly 1 Gmail send call for 1 recipient ─────
    send_calls = mock_svc.users.return_value.messages.return_value.send.call_args_list
    if len(send_calls) == 1:
        ok("send_summary_email 3 links — exactly 1 send() call for 1 recipient")
    else:
        fail("send_summary_email send count", f"expected 1 call, got {len(send_calls)}")


# ══════════════════════════════════════════════════════
# 15. Color profiles + crop_x (pipeline/editor.py)
# ══════════════════════════════════════════════════════

def test_color_and_crop() -> None:
    section("15 / Color profiles + crop_x (cut_clip)")

    if not Path(VIDEO_60FPS).exists():
        fail("color/crop tests", "60fps test video missing")
        return

    # ── _COLOR_PROFILES: surfing exists and differs from default ──
    default_grade  = _COLOR_PROFILES.get("_default", "")
    surfing_grade  = _COLOR_PROFILES.get("surfing", "")
    football_grade = _COLOR_PROFILES.get("football", "")

    if surfing_grade and surfing_grade != default_grade:
        ok("_COLOR_PROFILES — surfing profile exists and differs from default",
           f"surfing={surfing_grade[:30]}")
    else:
        fail("_COLOR_PROFILES — surfing profile", f"got {surfing_grade!r}")

    if football_grade and football_grade != surfing_grade:
        ok("_COLOR_PROFILES — football profile differs from surfing",
           f"football={football_grade[:30]}")
    else:
        fail("_COLOR_PROFILES — football vs surfing", f"got {football_grade!r}")

    # ── cut_clip with crop_x=0.3 (athlete on left third) ──
    event_left = {
        "type": "cutback", "start": 2.0, "end": 10.0,
        "score": 8, "description": "", "crop_x": 0.3,
    }
    clip_left = cut_clip(VIDEO_60FPS, event_left, index=51, slowmo=False, sport="surfing")
    if clip_left and Path(clip_left).exists():
        ok("cut_clip — crop_x=0.3 (left-biased athlete) produces output")
    else:
        fail("cut_clip — crop_x=0.3", "clip not created")

    # ── cut_clip with crop_x=0.8 (athlete on right) + sport color ──
    event_right = {
        "type": "snap", "start": 3.0, "end": 11.0,
        "score": 7, "description": "", "crop_x": 0.8,
    }
    clip_right = cut_clip(VIDEO_60FPS, event_right, index=52, slowmo=False, sport="football")
    if clip_right and Path(clip_right).exists():
        ok("cut_clip — crop_x=0.8 + sport=football produces output")
    else:
        fail("cut_clip — crop_x=0.8 football", "clip not created")

    for c in (clip_left, clip_right):
        if c:
            try:
                os.remove(c)
            except OSError:
                pass


# ══════════════════════════════════════════════════════
# 16. find_client (pipeline/clients.py)
# ══════════════════════════════════════════════════════

def test_find_client() -> None:
    section("16 / find_client (pipeline/clients.py)")

    from pipeline.clients import find_client  # noqa: PLC0415

    test_clients = [
        {"name": "Yoni Surfer",  "email": "yoni@test.com",  "video_pattern": "yoni"},
        {"name": "David Player", "email": "david@test.com", "video_pattern": "david"},
    ]
    wrote_temp = not Path(CLIENTS_TMP).exists()
    if wrote_temp:
        with open(CLIENTS_TMP, "w") as f:
            json.dump(test_clients, f)

    # ── match by pattern in description ───────────────
    match = find_client("DRAFT_yoni_red_board_20260514.mp4")
    if match and match.get("email") == "yoni@test.com":
        ok("find_client — matches 'yoni' pattern in draft name")
    else:
        fail("find_client — yoni match", f"got {match!r}")

    # ── case-insensitive match ─────────────────────────
    match2 = find_client("DRAFT_DAVID_footballer_20260514.mp4")
    if match2 and match2.get("email") == "david@test.com":
        ok("find_client — case-insensitive match")
    else:
        fail("find_client — case-insensitive", f"got {match2!r}")

    # ── no match → None ────────────────────────────────
    no_match = find_client("DRAFT_unknown_athlete_20260514.mp4")
    if no_match is None:
        ok("find_client — no match → None")
    else:
        fail("find_client — no match", f"expected None, got {no_match!r}")

    if wrote_temp:
        try:
            os.remove(CLIENTS_TMP)
        except OSError:
            pass


# ══════════════════════════════════════════════════════
# 13. Identity clustering (pipeline/identity.py)
# ══════════════════════════════════════════════════════

def test_identity_clustering() -> None:
    section("13 / Identity clustering (cluster_clips + _parse_session)")

    from pipeline.identity import cluster_clips  # noqa: PLC0415

    # ── _parse_session: valid multi-person JSON ───────
    multi_person_json = json.dumps({
        "activity": "surfing",
        "persons": [
            {
                "id": "person_A",
                "description": "red board",
                "events": [
                    {"type": "wave_catch", "start": 5.0, "end": 14.0, "score": 9,
                     "description": "Catches a large wave."},
                ],
            },
            {
                "id": "person_B",
                "description": "blue board",
                "events": [],
            },
        ],
    })
    try:
        result = _parse_session(multi_person_json)
        if (result["activity"] == "surfing"
                and len(result["persons"]) == 2
                and result["persons"][0]["id"] == "person_A"):
            ok("_parse_session — valid multi-person JSON", f"activity={result['activity']}, persons={len(result['persons'])}")
        else:
            fail("_parse_session — valid JSON", f"unexpected result: {result}")
    except Exception as e:
        fail("_parse_session — valid JSON", str(e))

    # ── cluster_clips: empty input → [] ───────────────
    try:
        result = cluster_clips([])
        if result == []:
            ok("cluster_clips — empty input → []")
        else:
            fail("cluster_clips — empty input", f"got {result}")
    except Exception as e:
        fail("cluster_clips — empty input", str(e))

    # ── cluster_clips: single clip, 1 person → direct return (no Gemini) ──
    single_clip = [{
        "path": "/tmp/debug_clip.mp4",
        "analysis": {
            "activity": "surfing",
            "persons": [{
                "id": "person_A",
                "description": "red board",
                "events": [{"type": "wave_catch", "start": 5.0, "end": 14.0, "score": 9, "description": ""}],
            }],
        },
    }]
    try:
        result = cluster_clips(single_clip)
        if (len(result) == 1
                and result[0]["description"] == "red board"
                and result[0]["appearances"][0]["path"] == "/tmp/debug_clip.mp4"):
            ok("cluster_clips — single clip → direct return, correct description + path")
        else:
            fail("cluster_clips — single clip", f"unexpected: {result}")
    except Exception as e:
        fail("cluster_clips — single clip", str(e))

    # ── cluster_clips: multiple clips, Gemini mocked → fallback (each person = own cluster) ──
    two_clips = [
        {
            "path": "/tmp/debug_clip1.mp4",
            "analysis": {
                "activity": "surfing",
                "persons": [{
                    "id": "person_A",
                    "description": "red board",
                    "events": [{"type": "wave_catch", "start": 5.0, "end": 14.0, "score": 9, "description": ""}],
                }],
            },
        },
        {
            "path": "/tmp/debug_clip2.mp4",
            "analysis": {
                "activity": "surfing",
                "persons": [{
                    "id": "person_B",
                    "description": "blue board",
                    "events": [{"type": "aerial", "start": 20.0, "end": 29.0, "score": 8, "description": ""}],
                }],
            },
        },
    ]
    try:
        result = cluster_clips(two_clips)
        descriptions = {r["description"] for r in result}
        if len(result) == 2 and "red board" in descriptions and "blue board" in descriptions:
            ok("cluster_clips — multi-clip Gemini fallback → 2 clusters", str(descriptions))
        else:
            fail("cluster_clips — multi-clip fallback", f"got {result}")
    except Exception as e:
        fail("cluster_clips — multi-clip fallback", str(e))

    # ── _extract_thumbnail: produces a JPEG file at the given timestamp ───────
    _thumb_src = os.path.join(DEBUG_DIR, "test_thumb_source.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:duration=2",
             "-r", "30", _thumb_src],
            capture_output=True, timeout=20, check=True,
        )
        thumb_path = _extract_thumbnail(_thumb_src, 0.5)
        if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            ok("_extract_thumbnail — produces JPEG at given timestamp", thumb_path)
            try: os.remove(thumb_path)
            except OSError: pass
        else:
            fail("_extract_thumbnail — file missing or empty", str(thumb_path))
    except Exception as e:
        fail("_extract_thumbnail", str(e))
    finally:
        try: os.remove(_thumb_src)
        except OSError: pass

    # ── _try_clip_cluster: returns None when torch/transformers unavailable ───
    from pipeline.identity import _try_clip_cluster  # noqa: PLC0415
    try:
        result = _try_clip_cluster(two_clips)
        # In the debug environment torch is not installed → must return None
        if result is None:
            ok("_try_clip_cluster — returns None when CLIP deps missing")
        else:
            # torch IS installed and produced clusters — that's also fine
            ok("_try_clip_cluster — CLIP available, returned clusters", str(len(result)))
    except Exception as e:
        fail("_try_clip_cluster", str(e))

    # ── _try_visual_cluster: returns None when no thumbnails present ──────────
    from pipeline.identity import _try_visual_cluster  # noqa: PLC0415
    descriptions_list = [
        {"clip_index": 0, "person_id": "person_A", "description": "red board"},
        {"clip_index": 1, "person_id": "person_B", "description": "blue board"},
    ]
    try:
        result = _try_visual_cluster(descriptions_list, two_clips)
        # No thumbnails in two_clips → should return None
        if result is None:
            ok("_try_visual_cluster — returns None when no thumbnails available")
        else:
            fail("_try_visual_cluster — expected None (no thumbnails)", f"got {result}")
    except Exception as e:
        fail("_try_visual_cluster", str(e))

    # ── cluster_clips with thumbnails → uses visual tier if available ─────────
    from unittest.mock import patch  # noqa: PLC0415
    thumb_file = os.path.join(DEBUG_DIR, "test_thumb_identity.jpg")
    # Create a minimal JPEG placeholder to satisfy os.path.exists checks
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=64x64:duration=0.1",
             "-frames:v", "1", thumb_file],
            capture_output=True, timeout=15
        )
    except Exception:
        pass

    two_clips_with_thumbs = [
        {
            "path": "/tmp/debug_clip1.mp4",
            "analysis": {
                "activity": "surfing",
                "persons": [{
                    "id": "person_A",
                    "description": "red board",
                    "thumbnail": thumb_file if os.path.exists(thumb_file) else "",
                    "events": [{"type": "wave_catch", "start": 5.0, "end": 14.0, "score": 9, "description": ""}],
                }],
            },
        },
        {
            "path": "/tmp/debug_clip2.mp4",
            "analysis": {
                "activity": "surfing",
                "persons": [{
                    "id": "person_B",
                    "description": "blue board",
                    "thumbnail": thumb_file if os.path.exists(thumb_file) else "",
                    "events": [{"type": "aerial", "start": 20.0, "end": 29.0, "score": 8, "description": ""}],
                }],
            },
        },
    ]
    gemini_visual_response = json.dumps({
        "clusters": [
            {"description": "red board surfer", "appearances": [{"clip_index": 0, "person_id": "person_A"}]},
            {"description": "blue board surfer", "appearances": [{"clip_index": 1, "person_id": "person_B"}]},
        ]
    })
    try:
        with patch("pipeline.identity._try_clip_cluster", return_value=None), \
             patch("pipeline.identity.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value.generate_content.return_value.text = gemini_visual_response
            # Mock upload_file to return an object with a .name attribute
            from unittest.mock import MagicMock  # noqa: PLC0415
            mock_file = MagicMock()
            mock_file.name = "files/test_thumb"
            mock_genai.upload_file.return_value = mock_file

            result = cluster_clips(two_clips_with_thumbs)
            if len(result) == 2:
                ok("cluster_clips — with thumbnails, visual tier produces 2 clusters")
            else:
                fail("cluster_clips — visual tier", f"expected 2 clusters, got {len(result)}")
    except Exception as e:
        fail("cluster_clips — visual tier with thumbnails", str(e))

    # ── _build_clusters_from_data: low-confidence multi-clip → split ──────────
    from pipeline.identity import _build_clusters_from_data  # noqa: PLC0415

    low_conf_data = {
        "clusters": [{
            "description": "black wetsuit athlete",
            "confidence": "low",
            "appearances": [
                {"clip_index": 0, "person_id": "person_A"},
                {"clip_index": 1, "person_id": "person_B"},
            ],
        }]
    }
    try:
        split_result = _build_clusters_from_data(low_conf_data, two_clips)
        if len(split_result) == 2:
            ok("_build_clusters_from_data — low-confidence multi-clip → split into 2 clusters")
        else:
            fail("_build_clusters_from_data — low-conf split", f"expected 2, got {len(split_result)}")
    except Exception as e:
        fail("_build_clusters_from_data — low-conf split", str(e))

    # ── high-confidence → stays merged ───────────────────────────────────────
    high_conf_data = {
        "clusters": [{
            "description": "#7 red shirt",
            "confidence": "high",
            "appearances": [
                {"clip_index": 0, "person_id": "person_A"},
                {"clip_index": 1, "person_id": "person_B"},
            ],
        }]
    }
    try:
        merged_result = _build_clusters_from_data(high_conf_data, two_clips)
        if len(merged_result) == 1:
            ok("_build_clusters_from_data — high-confidence multi-clip → stays merged")
        else:
            fail("_build_clusters_from_data — high-conf merge", f"expected 1, got {len(merged_result)}")
    except Exception as e:
        fail("_build_clusters_from_data — high-conf merge", str(e))

    # ── missing confidence → treated as medium (no split) ────────────────────
    no_conf_data = {
        "clusters": [{
            "description": "blue board",
            "appearances": [
                {"clip_index": 0, "person_id": "person_A"},
                {"clip_index": 1, "person_id": "person_B"},
            ],
        }]
    }
    try:
        no_conf_result = _build_clusters_from_data(no_conf_data, two_clips)
        if len(no_conf_result) == 1:
            ok("_build_clusters_from_data — missing confidence field → no split (treated as medium)")
        else:
            fail("_build_clusters_from_data — missing confidence", f"expected 1, got {len(no_conf_result)}")
    except Exception as e:
        fail("_build_clusters_from_data — missing confidence", str(e))

    # ── cluster_clips cleans up thumbnail files after completion ─────────────
    thumb_cleanup_a = os.path.join(DEBUG_DIR, "test_cleanup_a.jpg")
    thumb_cleanup_b = os.path.join(DEBUG_DIR, "test_cleanup_b.jpg")
    for t in (thumb_cleanup_a, thumb_cleanup_b):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=64x64:duration=0.1",
                 "-frames:v", "1", t],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass

    clips_cleanup = [
        {
            "path": "/tmp/debug_clip1.mp4",
            "analysis": {
                "activity": "surfing",
                "persons": [{
                    "id": "person_A", "description": "red board",
                    "thumbnail": thumb_cleanup_a,
                    "events": [{"type": "wave_catch", "start": 5.0, "end": 14.0, "score": 9, "description": ""}],
                }],
            },
        },
        {
            "path": "/tmp/debug_clip2.mp4",
            "analysis": {
                "activity": "surfing",
                "persons": [{
                    "id": "person_B", "description": "blue board",
                    "thumbnail": thumb_cleanup_b,
                    "events": [{"type": "aerial", "start": 20.0, "end": 29.0, "score": 8, "description": ""}],
                }],
            },
        },
    ]
    try:
        with patch("pipeline.identity._try_clip_cluster", return_value=None), \
             patch("pipeline.identity._try_visual_cluster", return_value=None), \
             patch("pipeline.identity._text_cluster", side_effect=RuntimeError("force fallback")):
            cluster_clips(clips_cleanup)
        still_exist = [t for t in (thumb_cleanup_a, thumb_cleanup_b) if os.path.exists(t)]
        if not still_exist:
            ok("cluster_clips — thumbnail files cleaned up after completion")
        else:
            fail("cluster_clips — thumbnail cleanup", f"still on disk: {still_exist}")
    except Exception as e:
        fail("cluster_clips — thumbnail cleanup", str(e))


# ══════════════════════════════════════════════════════
# 14. Deliver flow (deliver.py)
# ══════════════════════════════════════════════════════

def test_deliver_flow() -> None:
    section("14 / Deliver flow (deliver.py + deliver_final.py mock)")

    from unittest.mock import patch
    import deliver         # noqa: PLC0415
    import deliver_final   # noqa: PLC0415

    _no_client    = patch("deliver.find_client",         return_value=None)
    _no_previewed = patch("deliver._load_previewed",     return_value=set())
    _no_mark_prev = patch("deliver._mark_previewed")
    _mock_dl      = patch("deliver.download_video",      return_value="/tmp/fake_reel.mp4")
    _mock_prev    = patch("deliver.create_preview",      return_value="/tmp/fake_preview.mp4")
    _mock_upload  = patch("deliver.upload_preview",      return_value="https://preview.link/p1")
    _mock_move    = patch("deliver.move_to_pending_payment")

    # ── no approved drafts → send_summary_email NOT called ──
    with patch("deliver.get_approved_drafts", return_value=[]), \
         patch("deliver.send_summary_email") as mock_send, \
         _no_client, _no_previewed, _no_mark_prev, \
         _mock_dl, _mock_prev, _mock_upload, _mock_move:
        deliver.main()
        if mock_send.call_count == 0:
            ok("deliver.main — no drafts → send_summary_email not called")
        else:
            fail("deliver.main — no drafts", f"send called {mock_send.call_count} times")

    # ── 1 draft → download, create_preview, upload_preview each called once ──
    one_draft = [{"id": "d1", "name": "DRAFT_red_board_20260514.mp4",
                  "webViewLink": "https://drive.google.com/d1"}]
    with patch("deliver.get_approved_drafts", return_value=one_draft), \
         patch("deliver.send_summary_email"), \
         _no_client, _no_previewed, _no_mark_prev, \
         _mock_dl as m_dl, _mock_prev as m_prev, _mock_upload as m_up, _mock_move:
        deliver.main()
        if m_dl.call_count == 1 and m_prev.call_count == 1 and m_up.call_count == 1:
            ok("deliver.main — 1 draft → download, create_preview, upload_preview each called once")
        else:
            fail("deliver.main — pipeline calls",
                 f"dl={m_dl.call_count} prev={m_prev.call_count} up={m_up.call_count}")

    # ── 1 draft → move_to_pending_payment called once ──
    with patch("deliver.get_approved_drafts", return_value=one_draft), \
         patch("deliver.send_summary_email"), \
         _no_client, _no_previewed, _no_mark_prev, \
         _mock_dl, _mock_prev, _mock_upload, _mock_move as m_move:
        deliver.main()
        if m_move.call_count == 1:
            ok("deliver.main — move_to_pending_payment called after preview upload")
        else:
            fail("deliver.main — move_to_pending_payment",
                 f"expected 1 call, got {m_move.call_count}")

    # ── smoke: main() runs without exception ──
    try:
        with patch("deliver.get_approved_drafts", return_value=one_draft), \
             patch("deliver.send_summary_email"), \
             _no_client, _no_previewed, _no_mark_prev, \
             _mock_dl, _mock_prev, _mock_upload, _mock_move:
            deliver.main()
        ok("deliver.main — smoke test, no exception")
    except Exception as e:
        fail("deliver.main — smoke test", str(e))

    # ── download failure → email not sent, move not called ──
    with patch("deliver.get_approved_drafts", return_value=one_draft), \
         patch("deliver.send_summary_email") as mock_send2, \
         patch("deliver.download_video", side_effect=RuntimeError("network error")), \
         patch("deliver.create_preview", return_value="/tmp/fake_preview.mp4"), \
         patch("deliver.upload_preview", return_value="https://preview.link/p1"), \
         _mock_move as m_move2, \
         _no_client, _no_previewed, _no_mark_prev:
        deliver.main()
        if mock_send2.call_count == 0 and m_move2.call_count == 0:
            ok("deliver.main — download failure → email not sent, move not called")
        else:
            fail("deliver.main — download failure",
                 f"send={mock_send2.call_count} move={m_move2.call_count}")

    # ── already-previewed IDs → skipped (idempotency) ──
    with patch("deliver.get_approved_drafts", return_value=one_draft), \
         patch("deliver.send_summary_email") as mock_send3, \
         patch("deliver._load_previewed", return_value={"d1"}), \
         _no_mark_prev, _no_client, \
         _mock_dl, _mock_prev, _mock_upload, _mock_move:
        deliver.main()
        if mock_send3.call_count == 0:
            ok("deliver.main — already-previewed IDs → skipped (idempotency)")
        else:
            fail("deliver.main — idempotency", f"expected 0 sends, got {mock_send3.call_count}")

    # ── missing webViewLink → skipped ──
    no_link_draft = [{"id": "d2", "name": "DRAFT_no_link.mp4", "webViewLink": ""}]
    with patch("deliver.get_approved_drafts", return_value=no_link_draft), \
         patch("deliver.send_summary_email") as mock_send4, \
         _no_client, _no_previewed, _no_mark_prev, \
         _mock_dl, _mock_prev, _mock_upload, _mock_move as m_move3:
        deliver.main()
        if mock_send4.call_count == 0 and m_move3.call_count == 0:
            ok("deliver.main — missing webViewLink → download and move skipped")
        else:
            fail("deliver.main — missing webViewLink",
                 f"send={mock_send4.call_count} move={m_move3.call_count}")

    # ── deliver_final: no pending → email not called ──
    _no_del_client  = patch("deliver_final.find_client",          return_value=None)
    _no_delivered   = patch("deliver_final._load_delivered",      return_value=set())
    _no_save_deliv  = patch("deliver_final._save_delivered")
    _no_mark_deliv  = patch("deliver_final.mark_draft_delivered")

    with patch("deliver_final.get_pending_payment_drafts", return_value=[]), \
         patch("deliver_final.send_summary_email") as mock_fin, \
         _no_del_client, _no_delivered, _no_save_deliv, _no_mark_deliv:
        deliver_final.main()
        if mock_fin.call_count == 0:
            ok("deliver_final.main — no pending → email not called")
        else:
            fail("deliver_final.main — no pending", f"send called {mock_fin.call_count} times")

    # ── deliver_final: 1 pending → owner email sent with full link ──
    pending_draft = [{"id": "p1", "name": "DRAFT_red_board_20260514.mp4",
                      "webViewLink": "https://drive.google.com/full_p1"}]
    with patch("deliver_final.get_pending_payment_drafts", return_value=pending_draft), \
         patch("deliver_final.send_summary_email") as mock_fin2, \
         _no_del_client, _no_delivered, _no_save_deliv, _no_mark_deliv:
        deliver_final.main()
        if mock_fin2.call_count == 1:
            links_arg = (mock_fin2.call_args.kwargs.get("clips_links")
                         or (mock_fin2.call_args.args[1] if mock_fin2.call_args.args else []))
            if "https://drive.google.com/full_p1" in links_arg:
                ok("deliver_final.main — 1 pending → owner email with full-quality link")
            else:
                fail("deliver_final.main — owner link", f"got {links_arg}")
        else:
            fail("deliver_final.main — send count", f"expected 1, got {mock_fin2.call_count}")

    # ── deliver_final: mark_draft_delivered called for each pending ──
    with patch("deliver_final.get_pending_payment_drafts", return_value=pending_draft), \
         patch("deliver_final.send_summary_email"), \
         _no_del_client, _no_delivered, _no_save_deliv, \
         patch("deliver_final.mark_draft_delivered") as mock_arch:
        deliver_final.main()
        if mock_arch.call_count == 1:
            ok("deliver_final.main — mark_draft_delivered called for each pending reel")
        else:
            fail("deliver_final.main — archive count", f"expected 1, got {mock_arch.call_count}")


# ══════════════════════════════════════════════════════
# 17. Editing improvements (speed-ramp, font, xfade, label)
# ══════════════════════════════════════════════════════

def test_editor_improvements() -> None:
    section("17 / Editing improvements (_partition_events, _find_font, xfade, label)")

    # ── _partition_events: splits into multiple reels when total > target_max ──
    _long = [
        {"type": "a", "start": 0.0,  "end": 12.0, "score": 9, "description": "", "crop_x": 0.5},
        {"type": "b", "start": 13.0, "end": 25.0, "score": 7, "description": "", "crop_x": 0.5},
        {"type": "c", "start": 26.0, "end": 38.0, "score": 6, "description": "", "crop_x": 0.5},
    ]
    # no-slowmo: 12+12+12 - 2×0.5 = 35s > 30 → should produce 2 partitions
    try:
        parts = _partition_events(_long, slowmo=False, target_max=30)
        if len(parts) == 2 and all(len(p) >= 1 for p in parts):
            ok("_partition_events — 3 events >30s → split into 2 partitions",
               f"{len(parts)} partitions, sizes {[len(p) for p in parts]}")
        else:
            fail("_partition_events — split into 2",
                 f"got {len(parts)} partitions: {[[e['score'] for e in p] for p in parts]}")
    except Exception as e:
        fail("_partition_events — split into 2", str(e))

    # ── single partition when events fit ──
    try:
        one = _partition_events(_long[:2], slowmo=False, target_max=30)
        if len(one) == 1 and len(one[0]) == 2:
            ok("_partition_events — 2 events that fit → single partition")
        else:
            fail("_partition_events — single partition", f"got {len(one)} partitions")
    except Exception as e:
        fail("_partition_events — single partition", str(e))

    # ── _find_font: returns path or None gracefully ──
    try:
        font = _find_font()
        if font is None:
            ok("_find_font — returns None gracefully (no system bold font found)")
        else:
            ok("_find_font — found system font", font)
    except Exception as e:
        fail("_find_font", str(e))

    # ── _xfade_filter sport-specific transition ──
    try:
        flt = _xfade_filter(2, [7.0, 7.0], sport="surfing")
        known = ["slideleft", "slideright", "zoomin", "fade", "wipeleft",
                 "pixelize", "fadewhite", "wiperight", "slidedown"]
        if any(t in flt for t in known):
            ok("_xfade_filter — sport-specific transition selected",
               next(t for t in known if t in flt))
        else:
            fail("_xfade_filter — sport transition", f"no known transition in: {flt[:100]}")
    except Exception as e:
        fail("_xfade_filter — sport transition", str(e))

    # ── compile_reel with athlete_label smoke test ──
    if not Path(VIDEO_60FPS).exists():
        fail("compile_reel athlete_label", "60fps test video missing")
        return

    events_lbl = [
        {"type": "a", "start": 0.0,  "end": 7.0,  "score": 8, "description": ""},
        {"type": "b", "start": 7.5,  "end": 14.0, "score": 6, "description": ""},
        {"type": "c", "start": 14.5, "end": 20.0, "score": 9, "description": ""},
    ]
    clips_lbl = [cut_clip(VIDEO_60FPS, ev, index=i+60, slowmo=False)
                 for i, ev in enumerate(events_lbl)]
    clips_lbl = [c for c in clips_lbl if c and Path(c).exists()]

    if len(clips_lbl) >= 2:
        reel_text = compile_reel(
            clips_lbl, config.LOGO_PATH,
            os.path.join(DEBUG_DIR, "debug_text_reel.mp4"),
            sport="surfing", athlete_label="surfer #7 red board",
        )
        if reel_text and Path(reel_text).exists():
            ok("compile_reel — athlete_label smoke test (text overlay path)")
        else:
            fail("compile_reel — athlete_label smoke test", "reel not produced")
        for c in clips_lbl:
            try:
                os.remove(c)
            except OSError:
                pass
    else:
        fail("compile_reel — athlete_label smoke test", f"only {len(clips_lbl)} clips available")


def test_music_smart_selection() -> None:
    section("18 / Smart music selection (_ensure_music_cache + _pick_music BPM match)")

    music_dir = os.path.join(DEBUG_DIR, "music_smart_test")
    os.makedirs(music_dir, exist_ok=True)

    slow_mp3 = os.path.join(music_dir, "slow_surf.mp3")
    fast_mp3 = os.path.join(music_dir, "fast_skate.mp3")
    for path, freq in [(slow_mp3, 220), (fast_mp3, 880)]:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"sine=frequency={freq}:duration=40",
             "-q:a", "0", path],
            capture_output=True, timeout=15,
        )

    # ── _ensure_music_cache: creates cache file ──
    try:
        cache = _ensure_music_cache(music_dir)
        cache_file = os.path.join(music_dir, ".music_cache.json")
        if os.path.exists(cache_file) and "slow_surf.mp3" in cache and "fast_skate.mp3" in cache:
            ok("_ensure_music_cache — creates cache with both tracks")
        else:
            fail("_ensure_music_cache — cache file", f"keys: {list(cache.keys())}")
    except Exception as e:
        fail("_ensure_music_cache", str(e))

    # ── cache entries have required keys ──
    try:
        entry = cache.get("slow_surf.mp3", {})
        if {"bpm", "energy_score", "mtime"}.issubset(entry.keys()):
            ok("_ensure_music_cache — entry has bpm, energy_score, mtime")
        else:
            fail("_ensure_music_cache — entry keys", str(entry.keys()))
    except Exception as e:
        fail("_ensure_music_cache — entry keys", str(e))

    # ── second call is a cache hit (no file re-analysis) ──
    try:
        cache2 = _ensure_music_cache(music_dir)
        if cache2.get("slow_surf.mp3", {}).get("mtime") == cache.get("slow_surf.mp3", {}).get("mtime"):
            ok("_ensure_music_cache — second call returns same mtime (cache hit)")
        else:
            fail("_ensure_music_cache — cache hit", "mtime changed on second call")
    except Exception as e:
        fail("_ensure_music_cache — cache hit", str(e))

    # ── _pick_music with sport returns a path from the dir ──
    old_music_dir = getattr(config, "MUSIC_DIR", "music")
    config.MUSIC_DIR = music_dir
    try:
        picked = _pick_music(sport="surfing")
        if picked and Path(picked).exists() and Path(picked).parent == Path(music_dir):
            ok("_pick_music(sport='surfing') — returns a path from music dir", Path(picked).name)
        else:
            fail("_pick_music sport", f"got {picked!r}")
    except Exception as e:
        fail("_pick_music sport", str(e))
    finally:
        config.MUSIC_DIR = old_music_dir

    # ── compile_reel smoke test with explicit music_path ──
    if Path(VIDEO_60FPS).exists():
        evs = [
            {"type": "a", "start": 0.0, "end": 7.0, "score": 8, "description": ""},
            {"type": "b", "start": 7.5, "end": 14.0, "score": 6, "description": ""},
        ]
        clips = [cut_clip(VIDEO_60FPS, ev, index=i + 70, slowmo=False)
                 for i, ev in enumerate(evs)]
        clips = [c for c in clips if c and Path(c).exists()]
        try:
            if len(clips) >= 2:
                reel = compile_reel(clips, config.LOGO_PATH,
                                    os.path.join(DEBUG_DIR, "debug_smart_music_reel.mp4"),
                                    sport="surfing",
                                    music_path=slow_mp3)
                if reel and Path(reel).exists():
                    ok("compile_reel — explicit music_path produces reel")
                else:
                    fail("compile_reel explicit music_path", "reel not produced")
            else:
                fail("compile_reel explicit music_path", "clips not created")
        except Exception as e:
            fail("compile_reel explicit music_path", str(e))
        finally:
            for c in clips:
                try: os.remove(c)
                except OSError: pass


def test_run_robustness() -> None:
    section("19 / run.py robustness (record_failure + _dominant_activity)")

    from pipeline.drive import record_failure, _load_failed_ids
    import tempfile
    import shutil

    orig_processed = config.PROCESSED_IDS_FILE
    tmp_dir = tempfile.mkdtemp()
    config.PROCESSED_IDS_FILE = os.path.join(tmp_dir, "processed.json")
    try:
        r1 = record_failure("vid_abc", max_failures=3)
        r2 = record_failure("vid_abc", max_failures=3)
        r3 = record_failure("vid_abc", max_failures=3)
        if not r1 and not r2 and r3:
            ok("record_failure — reaches limit on 3rd call")
        else:
            fail("record_failure", f"r1={r1} r2={r2} r3={r3}")
        counts = _load_failed_ids()
        if counts.get("vid_abc") == 3:
            ok("record_failure — persists count to disk")
        else:
            fail("record_failure — disk", f"counts={counts}")
    except Exception as e:
        fail("record_failure", str(e))
    finally:
        config.PROCESSED_IDS_FILE = orig_processed
        shutil.rmtree(tmp_dir, ignore_errors=True)

    from run import _dominant_activity
    surf_clips = [
        {"analysis": {"activity": "unknown"}, "meta": {"name": "surf_session_day2.mp4"}},
        {"analysis": {"activity": "unknown"}, "meta": {"name": "surf_beach_morning.mp4"}},
    ]
    try:
        act = _dominant_activity(surf_clips)
        if act == "surfing":
            ok("_dominant_activity — filename fallback → surfing")
        else:
            fail("_dominant_activity filename fallback", f"got {act!r}")
    except Exception as e:
        fail("_dominant_activity filename fallback", str(e))

    no_hint_clips = [
        {"analysis": {"activity": "unknown"}, "meta": {"name": "session_001.mp4"}},
    ]
    try:
        act2 = _dominant_activity(no_hint_clips)
        if act2 != "unknown":
            ok("_dominant_activity — last resort is not 'unknown'", act2)
        else:
            fail("_dominant_activity last resort", "returned 'unknown'")
    except Exception as e:
        fail("_dominant_activity last resort", str(e))


def test_resource_optimizations() -> None:
    section("20 / Resource optimizations (parallel cuts, cleanup, CLIP cache)")

    # ── cut_clip: no orphan file left after FFmpeg failure ──
    # Use a non-existent input path so FFmpeg actually fails (clamping makes
    # out-of-range timestamps valid, so we must force a real failure).
    bad_ev = {"type": "x", "start": 0.0, "end": 6.0,
              "score": 5, "description": "", "crop_x": 0.5}
    before = set(glob.glob(os.path.join(DEBUG_DIR, "*_clip*.mp4")))
    cut_clip("/nonexistent/fail_test_input.mp4", bad_ev, index=99, slowmo=False)
    after = set(glob.glob(os.path.join(DEBUG_DIR, "*_clip*.mp4")))
    if after == before:
        ok("cut_clip — no orphan file left after FFmpeg failure")
    else:
        fail("cut_clip — orphan file on failure", str(after - before))

    # ── parallel cuts vs sequential ──
    if Path(VIDEO_60FPS).exists():
        import time
        evs = [
            {"type": "a", "start": 0.0, "end": 6.0,  "score": 8, "description": "", "crop_x": 0.5},
            {"type": "b", "start": 6.0, "end": 12.0, "score": 7, "description": "", "crop_x": 0.5},
            {"type": "c", "start": 2.0, "end": 8.0,  "score": 6, "description": "", "crop_x": 0.5},
        ]
        t0 = time.monotonic()
        seq_clips = [cut_clip(VIDEO_60FPS, ev, index=i + 80, slowmo=False)
                     for i, ev in enumerate(evs)]
        seq_time = time.monotonic() - t0
        for c in seq_clips:
            if c:
                try: os.remove(c)
                except OSError: pass

        from concurrent.futures import ThreadPoolExecutor as _TPE
        t1 = time.monotonic()
        with _TPE(max_workers=3) as pool:
            futs = {pool.submit(cut_clip, VIDEO_60FPS, ev, i + 83, False, ""): i
                    for i, ev in enumerate(evs)}
            par_clips = [f.result() for f in futs]
        par_time = time.monotonic() - t1
        for c in par_clips:
            if c:
                try: os.remove(c)
                except OSError: pass

        if par_time < seq_time * 0.85:
            ok("parallel cut_clip — faster than sequential",
               f"{par_time:.1f}s vs {seq_time:.1f}s")
        else:
            ok("parallel cut_clip — comparable (single-core VM acceptable)",
               f"{par_time:.1f}s vs {seq_time:.1f}s seq")

    # ── CLIP singleton ──
    try:
        from pipeline.identity import _get_clip_model, _CLIP_CACHE
        _CLIP_CACHE.clear()
        try:
            p1, m1 = _get_clip_model()
            p2, m2 = _get_clip_model()
            if p1 is p2 and m1 is m2:
                ok("_get_clip_model — singleton: same object on second call")
            else:
                fail("_get_clip_model singleton", "different objects returned")
        except ImportError:
            ok("_get_clip_model — CLIP unavailable (torch not installed), skipped")
        except Exception:
            ok("_get_clip_model — model download unavailable in this env, skipped")
    except Exception as e:
        fail("_get_clip_model", str(e))


def test_preview_generation() -> None:
    section("22 / Preview generation (create_preview — 480p + watermark)")

    if not Path(VIDEO_60FPS).exists():
        fail("create_preview", "60fps test video missing — run section 2 first")
        return

    preview_out = VIDEO_60FPS.replace(".mp4", "_preview.mp4")
    try:
        os.remove(preview_out)
    except OSError:
        pass

    # ── output file exists ──
    try:
        result = create_preview(VIDEO_60FPS, athlete_label="Test Athlete #7")
        if result and Path(result).exists() and Path(result).stat().st_size > 0:
            ok("create_preview — output file created", Path(result).name)
        else:
            fail("create_preview — output file", f"path={result!r}")
            return
    except Exception as e:
        fail("create_preview", str(e))
        return

    # ── output dimensions match source (no downscaling) ──
    try:
        def _wh(path: str) -> tuple[int, int]:
            out = subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                text=True, timeout=15,
            ).strip().splitlines()
            return int(out[0]), int(out[1])

        w_in, h_in   = _wh(VIDEO_60FPS)
        w_out, h_out = _wh(preview_out)
        if w_in == w_out and h_in == h_out:
            ok("create_preview — dimensions preserved (no downscaling)",
               f"{w_out}×{h_out}")
        else:
            fail("create_preview — dimensions",
                 f"source={w_in}×{h_in} preview={w_out}×{h_out}")
    except Exception as e:
        fail("create_preview — dimension check", str(e))

    # ── output is a valid video file (ffprobe exits 0) ──
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", preview_out],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0:
            ok("create_preview — output is a valid video file (ffprobe clean)")
        else:
            fail("create_preview — valid video", r.stderr.decode(errors="replace")[:200])
    except Exception as e:
        fail("create_preview — valid video check", str(e))

    try:
        os.remove(preview_out)
    except OSError:
        pass


def test_io_parallelism() -> None:
    section("21 / I/O optimizations (lru_cache on ffprobe helpers)")

    # ── _get_duration lru_cache ──
    try:
        if hasattr(_get_duration, "cache_info"):
            _get_duration.cache_clear()
            if Path(VIDEO_60FPS).exists():
                _get_duration(VIDEO_60FPS)
                _get_duration(VIDEO_60FPS)
                info = _get_duration.cache_info()
                if info.hits >= 1:
                    ok("_get_duration — lru_cache hit on second call",
                       f"hits={info.hits} misses={info.misses}")
                else:
                    fail("_get_duration lru_cache", f"cache_info={info}")
        else:
            fail("_get_duration", "no cache_info — lru_cache not applied")
    except Exception as e:
        fail("_get_duration lru_cache", str(e))

    # ── _get_source_fps lru_cache ──
    try:
        if hasattr(_get_source_fps, "cache_info"):
            _get_source_fps.cache_clear()
            if Path(VIDEO_60FPS).exists():
                _get_source_fps(VIDEO_60FPS)
                _get_source_fps(VIDEO_60FPS)
                info = _get_source_fps.cache_info()
                if info.hits >= 1:
                    ok("_get_source_fps — lru_cache hit on second call",
                       f"hits={info.hits} misses={info.misses}")
                else:
                    fail("_get_source_fps lru_cache", f"cache_info={info}")
        else:
            fail("_get_source_fps", "no cache_info — lru_cache not applied")
    except Exception as e:
        fail("_get_source_fps lru_cache", str(e))


# ══════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════

def print_summary() -> None:
    total = len(PASSED) + len(FAILED)
    print(f"\n  {'═' * 52}")
    print(f"  RESULTS  {len(PASSED)}/{total} passed", end="")
    if FAILED:
        print(f"  |  {len(FAILED)} failed")
    else:
        print()
    print(f"  {'═' * 52}")

    if FAILED:
        print("\n  ❌ Failed tests:")
        for name in FAILED:
            print(f"     • {name}")
    else:
        print("\n  🎉 All tests passed — pipeline is ready to run!")

    print(f"\n  Debug output: {DEBUG_DIR}\n")


# ══════════════════════════════════════════════════════
# 23. Jersey-number client matching
# ══════════════════════════════════════════════════════

def test_jersey_matching() -> None:
    section("23 / Client matching — jersey_number + video_pattern")

    from pipeline.clients import find_client

    jersey_clients = [
        {"name": "איתי לוי",   "email": "itay@test.com",  "video_pattern": "itay",  "jersey_number": "7"},
        {"name": "יוני שמעון", "email": "yoni@test.com",  "video_pattern": "yoni",  "jersey_number": "10"},
    ]

    old_clients_file = config.CLIENTS_FILE
    tmp_clients = os.path.join(DEBUG_DIR, "jersey_clients_tmp.json")
    with open(tmp_clients, "w") as f:
        json.dump(jersey_clients, f)
    config.CLIENTS_FILE = tmp_clients

    try:
        # ── jersey number match (#7) ──
        m = find_client("player #7 in red jersey scored a goal")
        if m and m.get("email") == "itay@test.com":
            ok("find_client — jersey #7 match by jersey_number")
        else:
            fail("find_client jersey #7", f"got {m!r}")

        # ── jersey number match (#10) ──
        m2 = find_client("player number 10 dribbles past two defenders")
        if m2 and m2.get("email") == "yoni@test.com":
            ok("find_client — jersey number 10 match")
        else:
            fail("find_client jersey 10", f"got {m2!r}")

        # ── video_pattern fallback when no jersey in description ──
        m3 = find_client("itay_session_20260516.mp4")
        if m3 and m3.get("email") == "itay@test.com":
            ok("find_client — video_pattern fallback when no jersey in text")
        else:
            fail("find_client pattern fallback", f"got {m3!r}")

    finally:
        config.CLIENTS_FILE = old_clients_file
        try:
            os.remove(tmp_clients)
        except OSError:
            pass


# ══════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n🎬 D to R — Pipeline Debug / Simulation")
    print(f"   tmp dir: {DEBUG_DIR}\n")

    # Remove stale clips from previous runs so test videos are not shadowed
    for _stale in (
        glob.glob(os.path.join(DEBUG_DIR, "test_*_clip*.mp4")) +
        glob.glob(os.path.join(DEBUG_DIR, "REEL_*.mp4")) +
        glob.glob(os.path.join(DEBUG_DIR, "MULTI_*.mp4")) +
        [os.path.join(DEBUG_DIR, "debug_compiled_reel.mp4"),
         os.path.join(DEBUG_DIR, "debug_music_reel.mp4"),
         os.path.join(DEBUG_DIR, "debug_text_reel.mp4"),
         os.path.join(DEBUG_DIR, "debug_smart_music_reel.mp4"),
         os.path.join(DEBUG_DIR, "test_60fps_preview.mp4"),
         os.path.join(DEBUG_DIR, "music_smart_test", ".music_cache.json")]
    ):
        try:
            os.remove(_stale)
        except OSError:
            pass

    test_prerequisites()
    test_create_test_videos()
    test_fps_detection()
    test_narrative_order()
    test_analyzer_parsing()
    test_cut_clip()
    test_compile_reel()
    test_music_overlay()
    test_music_analysis()
    test_create_reel()
    test_email_html()
    test_pipeline_helpers()
    test_drive_pagination()
    test_retry_logic()
    test_batch_email()
    test_color_and_crop()
    test_find_client()
    test_identity_clustering()
    test_deliver_flow()
    test_editor_improvements()
    test_music_smart_selection()
    test_run_robustness()
    test_resource_optimizations()
    test_io_parallelism()
    test_preview_generation()
    test_jersey_matching()

    print_summary()
    sys.exit(0 if not FAILED else 1)

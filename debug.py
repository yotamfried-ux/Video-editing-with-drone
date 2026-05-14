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
os.environ.setdefault("OWNER_EMAIL",                 "debug@example.com")
os.environ.setdefault("LOGO_PATH",                   "assets/logo.png")
os.environ.setdefault("TMP_DIR",                     "/tmp/dtor_debug")

import config  # noqa: E402
from pipeline.editor   import (  # noqa: E402
    create_reel, cut_clip, compile_reel,
    _narrative_order, _get_source_fps, _get_duration, _pick_music,
    _analyze_music, analyze_music_library, _compute_cut_times,
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

from pipeline.analyzer import _parse_analysis, _parse_session, _with_retry  # noqa: E402
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

        if 1.7 < ratio < 2.3:
            ok("cut_clip slow-mo ≈2x duration", f"{dur_normal:.1f}s → {dur_slowmo:.1f}s (×{ratio:.2f})")
        else:
            fail("cut_clip slow-mo duration", f"ratio {ratio:.2f} (expected ~2.0)")
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
    result   = compile_reel(clips, config.LOGO_PATH, reel_out)

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

    t0   = time.time()
    reel = create_reel(VIDEO_60FPS, events, sport="surfing")
    dt   = time.time() - t0

    if reel and Path(reel).exists():
        kb  = Path(reel).stat().st_size // 1024
        dur = _get_duration(reel)
        ok("create_reel end-to-end", f"{dur:.1f}s reel, {kb}KB in {dt:.1f}s")
        print(f"       → {reel}")
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

    # multiple files → clips_session regardless of size
    multi = [
        {"id": "a", "name": "clip1.mp4", "size": "200000000"},
        {"id": "b", "name": "clip2.mp4", "size": "200000000"},
    ]
    if _classify_input(multi) == "clips_session":
        ok("_classify_input — multiple files → clips_session")
    else:
        fail("_classify_input — multiple files", f"got {_classify_input(multi)!r}")

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


# ══════════════════════════════════════════════════════
# 14. Deliver flow (deliver.py)
# ══════════════════════════════════════════════════════

def test_deliver_flow() -> None:
    section("14 / Deliver flow (deliver.main mock)")

    from unittest.mock import patch, MagicMock, call
    import deliver  # noqa: PLC0415

    # ── no approved drafts → send_summary_email NOT called ──
    with patch("deliver.get_approved_drafts", return_value=[]), \
         patch("deliver.send_summary_email") as mock_send, \
         patch("deliver.mark_draft_delivered"):
        deliver.main()
        if mock_send.call_count == 0:
            ok("deliver.main — no drafts → send_summary_email not called")
        else:
            fail("deliver.main — no drafts", f"send called {mock_send.call_count} times")

    # ── 2 approved drafts → send_summary_email called with 2 links ──
    drafts = [
        {"id": "d1", "name": "DRAFT_red_board_20260514.mp4",  "webViewLink": "https://drive.google.com/d1"},
        {"id": "d2", "name": "DRAFT_blue_board_20260514.mp4", "webViewLink": "https://drive.google.com/d2"},
    ]
    with patch("deliver.get_approved_drafts", return_value=drafts), \
         patch("deliver.send_summary_email") as mock_send, \
         patch("deliver.mark_draft_delivered"):
        deliver.main()
        if mock_send.call_count == 1:
            kwargs = mock_send.call_args.kwargs if mock_send.call_args.kwargs else {}
            links_arg = kwargs.get("clips_links", mock_send.call_args.args[1] if mock_send.call_args.args else [])
            if set(links_arg) == {"https://drive.google.com/d1", "https://drive.google.com/d2"}:
                ok("deliver.main — 2 drafts → send_summary_email called with 2 links")
            else:
                fail("deliver.main — send links", f"got links: {links_arg}")
        else:
            fail("deliver.main — send count", f"expected 1 call, got {mock_send.call_count}")

    # ── 2 approved drafts → mark_draft_delivered called twice ──
    with patch("deliver.get_approved_drafts", return_value=drafts), \
         patch("deliver.send_summary_email"), \
         patch("deliver.mark_draft_delivered") as mock_mark:
        deliver.main()
        if mock_mark.call_count == 2:
            ok("deliver.main — mark_draft_delivered called for each draft")
        else:
            fail("deliver.main — mark count", f"expected 2, got {mock_mark.call_count}")

    # ── smoke: main() runs without exception with mocked API ──
    try:
        with patch("deliver.get_approved_drafts", return_value=drafts), \
             patch("deliver.send_summary_email"), \
             patch("deliver.mark_draft_delivered"):
            deliver.main()
        ok("deliver.main — smoke test, no exception")
    except Exception as e:
        fail("deliver.main — smoke test", str(e))


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
# Entry point
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n🎬 D to R — Pipeline Debug / Simulation")
    print(f"   tmp dir: {DEBUG_DIR}\n")

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
    test_identity_clustering()
    test_deliver_flow()

    print_summary()
    sys.exit(0 if not FAILED else 1)

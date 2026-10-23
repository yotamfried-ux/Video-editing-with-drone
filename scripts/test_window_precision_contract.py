#!/usr/bin/env python3
"""Contract: the LLM reports exact event boundaries and nothing downstream pads or stretches them.

Real run 39726001357: 8 of 16 draft windows were extended by 3-6s of blind tail padding, 11 of 16
started at second 0.0, and the analysis prompt itself asked the model to "include 1-2s buildup".
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_import_stubs() -> None:
    sys.modules["config"] = types.SimpleNamespace(GEMINI_MODEL="test", TMP_DIR="/tmp", MIN_EVENT_SEC=5, QA_DUR_OK_MIN=1, QA_DUR_OK_MAX=120, QA_ENGAGEMENT_THRESHOLD=50)
    sys.modules["langsmith"] = types.SimpleNamespace(traceable=lambda *a, **k: (lambda fn: fn))
    sys.modules["integrations.gemini"] = types.SimpleNamespace(genai=types.SimpleNamespace(upload_file=lambda *a, **k: None, delete_file=lambda *a, **k: None), upload_video=lambda *a, **k: None, delete_video=lambda *a, **k: None)
    sys.modules["integrations.ffmpeg"] = types.SimpleNamespace(get_reel_specs=lambda _path: {"aspect": 9 / 16, "duration": 30, "height": 1920, "width": 1080, "has_audio": True})


def _session(**event) -> str:
    base = {"type": "wave_catch", "start": 10.0, "end": 15.5, "score": 8, "description": "x", "crop_x": 0.5, "crop_y": 0.6}
    return json.dumps({"activity": "surfing", "persons": [{"id": "p1", "description": "surfer", "events": [{**base, **event}]}]})


def test_prompt_asks_for_exact_boundaries() -> None:
    import pipeline.stages.analyzer as analyzer
    prompt = analyzer._IDENTITY_PROMPT
    assert "include 1-2s buildup" not in prompt and "minimum 6s after start" not in prompt, "old padding instructions must be gone"
    for token in ("timing_evidence", "NEVER start while the athlete is paddling", "never\n    stretch `end`"):
        assert token in prompt, f"prompt missing: {token!r}"
    assert "OPTIONAL" in prompt.split("setup_start:", 1)[1][:20], "phase fields stay optional"


def test_precise_event_is_not_padded_and_legacy_event_still_is() -> None:
    import pipeline.stages.analyzer as analyzer
    precise = analyzer._parse_session(_session(timing_evidence="start 10.0s: pops up; end 15.5s: falls"))["persons"][0]["events"][0]
    assert precise["timing_precise"] is True and precise["end"] == 15.5, precise
    assert precise["timing_evidence"].startswith("start 10.0s")
    legacy = analyzer._parse_session(_session())["persons"][0]["events"][0]
    assert legacy["timing_precise"] is False and legacy["end"] == 16.0, legacy   # legacy: padded to 6s
    blank = analyzer._parse_session(_session(timing_evidence="   "))["persons"][0]["events"][0]
    assert blank["timing_precise"] is False
    single = analyzer._parse_analysis(json.dumps({"activity": "surfing", "events": [{"type": "wave_catch", "start": 10, "end": 15.5, "score": 8, "timing_evidence": "start: stands; end: falls"}]}))["events"][0]
    assert single["timing_precise"] is True and single["end"] == 15.5, single
    too_short = analyzer._parse_session(_session(end=13.0, timing_evidence="start: a; end: b"))["persons"][0]["events"]
    assert too_short == [], "events under MIN_EVENT_SEC are still dropped, never stretched"


def test_cut_window_guard_leaves_precise_windows_alone() -> None:
    from pipeline.cut_window_guard import apply_cut_window_guard, needs_cut_window_guard
    legacy = {"type": "cutback", "start": 10, "end": 17, "description": "surfer on wave"}
    assert apply_cut_window_guard(legacy, 40, "surfing")["outcome_end"] == 20, "legacy tail padding must stay"
    for flag in ("timing_precise", "window_refined"):
        event = {**legacy, flag: True}
        assert not needs_cut_window_guard(event, "surfing")
        assert apply_cut_window_guard(event, 40, "surfing") == event, flag


def test_short_sources_are_sampled_at_higher_fps_and_the_cache_key_follows() -> None:
    import pipeline.stages.analyzer as analyzer
    for name in ("ANALYSIS_VIDEO_FPS", "ANALYSIS_SHORT_VIDEO_FPS", "ANALYSIS_SHORT_VIDEO_MAX_SEC", "ANALYSIS_MEDIA_RESOLUTION"):
        os.environ.pop(name, None)
    assert analyzer._analysis_call_options() == {}, "unknown duration keeps the SDK default"
    assert analyzer._analysis_call_options(None, 37.0) == {"video_metadata": {"fps": 4.0}}
    assert analyzer._analysis_call_options(None, 90.0) == {}, "long sources keep 1 fps"
    assert analyzer._analysis_call_options((2.0, 20.0), 37.0) == {"video_metadata": {"fps": 4.0, "start_offset": "2.0s", "end_offset": "20.0s"}}
    os.environ["ANALYSIS_VIDEO_FPS"] = "1"
    try:
        assert analyzer._analysis_call_options(None, 37.0) == {"video_metadata": {"fps": 1.0}}, "explicit fps wins"
    finally:
        os.environ.pop("ANALYSIS_VIDEO_FPS", None)
    os.environ["ANALYSIS_SHORT_VIDEO_MAX_SEC"] = "20"
    try:
        assert analyzer._analysis_call_options(None, 37.0) == {}
    finally:
        os.environ.pop("ANALYSIS_SHORT_VIDEO_MAX_SEC", None)
    from integrations import llm_cache
    key_a = llm_cache.make_key("analyze-session", media_sha256="m", prompt="p", model="x", extra=json.dumps([analyzer._analysis_call_options(None, 37.0)], sort_keys=True))
    key_b = llm_cache.make_key("analyze-session", media_sha256="m", prompt="p", model="x", extra=json.dumps([analyzer._analysis_call_options(None, 90.0)], sort_keys=True))
    assert key_a != key_b, "a different fps must never reuse a cached response"


def _det(time_sec: float, track: int | None = 7):
    from pipeline.perception.schema import PerceptionDetection
    return PerceptionDetection(source_video="s.mp4", frame_index=int(time_sec * 30), time_sec=time_sec, xyxy=(100, 100, 200, 300),
                               frame_width=1920, frame_height=1080, confidence=0.9, tracker_id=track)


def test_refinement_trims_to_the_tracked_span_and_only_ever_shrinks() -> None:
    from pipeline.window_refinement import refine_event_window
    dets = [_det(t / 2) for t in range(8, 25)]            # track 7 visible 4.0s..12.0s, every 0.5s
    event = {"start": 0.0, "end": 16.0, "target_track_id": "7", "setup_start": 1.0, "outcome_end": 15.0, "peak_time": 8.0}
    out = refine_event_window(event, dets)
    assert out["window_refined"] is True
    assert out["start"] == 3.5 and out["end"] == 13.0, out          # first-0.5, last+1.0
    assert out["llm_start"] == 0.0 and out["llm_end"] == 16.0
    assert out["setup_start"] is None and out["outcome_end"] == 13.0 and out["peak_time"] == 8.0
    assert out["window_refinement"]["reasons"] == ["athlete_not_in_frame_at_start", "track_lost_before_end"]
    assert event["start"] == 0.0 and "window_refined" not in event, "input must not be mutated"
    assert out["start"] >= event["start"] and out["end"] <= event["end"]

    # the window is then consumed unchanged by the editor's window policy
    from pipeline.window_policy import resolve_window
    resolved = resolve_window(out, 40.0)
    assert resolved and resolved["final_cut_start"] == 3.5 and resolved["final_cut_end"] == 13.0, resolved


def test_refinement_is_conservative() -> None:
    from pipeline.window_refinement import refine_event_window
    full = [_det(t / 2) for t in range(0, 33)]            # tracked 0..16s
    event = {"start": 0.0, "end": 16.0, "target_track_id": "7"}
    assert refine_event_window(event, full)["window_refinement"]["status"] == "unchanged"
    assert "window_refined" not in refine_event_window(event, full)
    assert refine_event_window({**event, "target_track_id": None}, full) is not None
    assert refine_event_window({"start": 0.0, "end": 16.0}, full) == {"start": 0.0, "end": 16.0}, "no track binding -> untouched"
    assert refine_event_window(event, [_det(5.0), _det(5.5)]) == event, "too few detections -> untouched"
    assert refine_event_window(event, [_det(t / 2, track=9) for t in range(0, 33)]) == event, "other track only -> untouched"
    short = [_det(t / 2) for t in range(16, 21)]           # tracked 8.0..10.0s: would leave 3s
    skipped = refine_event_window(event, short)
    assert skipped["window_refinement"]["status"] == "skipped_too_short" and skipped["start"] == 0.0 and skipped["end"] == 16.0
    sparse = [_det(t) for t in (0.0, 4.0, 8.0, 12.0)]       # 4s sampling gap: 3x gap tolerance, not 1.5s
    assert "window_refined" not in refine_event_window({"start": 0.0, "end": 16.0, "target_track_id": "7"}, sparse), "sparse sampling must not look like a lost track"


def test_runtime_enrichment_applies_refinement_and_the_kill_switch() -> None:
    import pipeline.perception.runtime as runtime
    dets = [_det(t / 2) for t in range(8, 25)]
    original_load = runtime.load_sidecar_detections
    runtime.load_sidecar_detections = lambda _path: dets
    try:
        session = {"persons": [{"id": "p1", "events": [{"start": 0.0, "end": 16.0, "crop_x": 0.15, "crop_y": 0.4}]}]}
        out = runtime.enrich_session_with_sidecar(session, "s.mp4")["persons"][0]["events"][0]
        assert out["window_refined"] is True and out["start"] == 3.5 and out["end"] == 13.0, out
        os.environ["WINDOW_REFINE"] = "0"
        off = runtime.enrich_session_with_sidecar(session, "s.mp4")["persons"][0]["events"][0]
        assert off["start"] == 0.0 and off["end"] == 16.0 and "window_refined" not in off, off
    finally:
        runtime.load_sidecar_detections = original_load
        os.environ.pop("WINDOW_REFINE", None)


def main() -> int:
    _install_import_stubs()
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print("Window precision contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

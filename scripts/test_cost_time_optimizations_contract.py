#!/usr/bin/env python3
"""Contract for the cost/time optimizations: analysis cache, concurrent analysis, QA min duration,
LLM call options, durable logging. No network, SDK or ffmpeg needed."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _stub_modules() -> None:
    sys.modules["config"] = types.SimpleNamespace(
        GEMINI_MODEL="test-model", TMP_DIR=tempfile.gettempdir(), MIN_EVENT_SEC=5, QA_DUR_OK_MIN=5,
        QA_DUR_OK_MAX=90, QA_ENGAGEMENT_THRESHOLD=60, CLIPS_CACHE_DIR=tempfile.gettempdir())
    sys.modules["langsmith"] = types.SimpleNamespace(traceable=lambda *a, **k: (lambda fn: fn))
    sys.modules["integrations.gemini"] = types.SimpleNamespace(
        genai=types.SimpleNamespace(upload_file=lambda *a, **k: None, delete_file=lambda *a, **k: None),
        upload_video=lambda *a, **k: None, delete_video=lambda *a, **k: None)
    sys.modules["integrations.ffmpeg"] = types.SimpleNamespace(
        get_reel_specs=lambda _p: {"aspect": 9 / 16, "duration": 30, "height": 1920, "width": 1080, "has_audio": True})


SESSION = json.dumps({"activity": "surfing", "persons": [{"id": "p1", "description": "surfer", "events": [
    {"type": "ride", "start": 10, "end": 22, "score": 8, "description": "x"}]}]})


def test_qa_minimum_duration_default_is_five_seconds() -> None:
    text = (ROOT / "config" / "settings.py").read_text()
    assert 'os.getenv("QA_DUR_OK_MIN", "5")' in text


def test_cache_key_changes_with_media_prompt_model_and_version() -> None:
    from integrations import llm_cache
    base = dict(media_sha256="a" * 64, prompt="p", model="m", version="1")
    key = llm_cache.make_key("k", **base)
    assert key == llm_cache.make_key("k", **base)
    for change in ({"media_sha256": "b" * 64}, {"prompt": "p2"}, {"model": "m2"}, {"version": "2"}):
        assert llm_cache.make_key("k", **{**base, **change}) != key, change


def test_cache_roundtrip_disable_and_fail_open() -> None:
    from integrations import llm_cache
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LLM_CACHE_DIR"] = tmp
        try:
            assert llm_cache.get("x" * 64) is None
            llm_cache.put("x" * 64, "hello", model="m")
            assert llm_cache.get("x" * 64) == "hello"
            os.environ["LLM_CACHE"] = "0"
            assert llm_cache.get("x" * 64) is None
            llm_cache.put("y" * 64, "nope")
            os.environ.pop("LLM_CACHE")
            assert llm_cache.get("y" * 64) is None
            (Path(tmp) / "zz").mkdir()
            (Path(tmp) / "zz" / f"{'z' * 64}.json").write_text("{broken")
            assert llm_cache.get("z" * 64) is None  # corrupt entry never raises
        finally:
            os.environ.pop("LLM_CACHE_DIR", None)
            os.environ.pop("LLM_CACHE", None)


def test_analysis_cache_hit_skips_gemini_and_a_miss_stores() -> None:
    _stub_modules()
    import pipeline.stages.analyzer as analyzer
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LLM_CACHE_DIR"] = tmp
        video = Path(tmp) / "source.mp4"
        video.write_bytes(b"not really a video")
        calls = {"gemini": 0, "upload": 0}
        sys.modules["pipeline.stages.feedback"] = types.SimpleNamespace(
            get_all_label_injections=lambda: "", get_operator_notes=lambda: "", get_negative_feedback_hint=lambda: "")
        analyzer._make_proxy = lambda path: None
        analyzer._upload_video = lambda path: (calls.__setitem__("upload", calls["upload"] + 1) or types.SimpleNamespace(name="f"))
        analyzer._delete_video = lambda vf: None
        analyzer._chunk_video = lambda path, *a, **k: [path]
        analyzer._extract_thumbnail = lambda *a, **k: None

        def fake_call(vf, prompt, model_name, video_name, trim_window=None):
            calls["gemini"] += 1
            return SESSION
        analyzer._gemini_call_session = fake_call
        try:
            first = analyzer.analyze_session(str(video))
            second = analyzer.analyze_session(str(video))
            assert calls == {"gemini": 1, "upload": 1}, calls
            assert first["persons"][0]["events"][0]["start"] == second["persons"][0]["events"][0]["start"]
            video.write_bytes(b"different footage")           # new content → miss
            analyzer.analyze_session(str(video))
            assert calls["gemini"] == 2, calls
            analyzer._IDENTITY_PROMPT = analyzer._IDENTITY_PROMPT + "\nchanged"   # new prompt → miss
            analyzer.analyze_session(str(video))
            assert calls["gemini"] == 3, calls
        finally:
            os.environ.pop("LLM_CACHE_DIR", None)


def test_analysis_call_options_are_opt_in() -> None:
    _stub_modules()
    import pipeline.stages.analyzer as analyzer
    for name in ("ANALYSIS_MEDIA_RESOLUTION", "ANALYSIS_VIDEO_FPS"):
        os.environ.pop(name, None)
    assert analyzer._analysis_call_options() == {}
    os.environ["ANALYSIS_MEDIA_RESOLUTION"] = "LOW"
    os.environ["ANALYSIS_VIDEO_FPS"] = "0.5"
    try:
        assert analyzer._analysis_call_options() == {"media_resolution": "LOW", "video_metadata": {"fps": 0.5}}
        os.environ["ANALYSIS_VIDEO_FPS"] = "fast"
        assert analyzer._analysis_call_options() == {"media_resolution": "LOW"}
    finally:
        os.environ.pop("ANALYSIS_MEDIA_RESOLUTION", None)
        os.environ.pop("ANALYSIS_VIDEO_FPS", None)


def test_activity_window_trims_only_head_and_tail_and_fails_open() -> None:
    from pipeline.activity_window import compute_window
    times = [40.0, 55.0, 70.0, 100.0]
    assert compute_window(times, 200.0) == (32.0, 108.0)                  # 8s padding either side
    assert compute_window([5.0, 100.0, 190.0], 200.0) is None             # <20% saved → whole video
    assert compute_window([40.0, 41.0], 200.0) is None                    # too little evidence
    assert compute_window([], 200.0) is None and compute_window(times, 0.0) is None
    assert compute_window([-5.0, 40.0, 50.0, 60.0, 9999.0], 200.0) == (32.0, 68.0)   # junk timestamps ignored


def test_trim_window_becomes_gemini_offsets_and_changes_the_cache_key() -> None:
    _stub_modules()
    import pipeline.stages.analyzer as analyzer
    os.environ.pop("ANALYSIS_VIDEO_FPS", None)
    assert analyzer._analysis_call_options((32.0, 108.0)) == {"video_metadata": {"start_offset": "32.0s", "end_offset": "108.0s"}}
    os.environ["ANALYSIS_VIDEO_FPS"] = "0.5"
    try:
        assert analyzer._analysis_call_options((32.0, 108.0))["video_metadata"] == {"fps": 0.5, "start_offset": "32.0s", "end_offset": "108.0s"}
    finally:
        os.environ.pop("ANALYSIS_VIDEO_FPS", None)


def test_concurrent_analysis_keeps_order_isolates_failures_and_is_faster() -> None:
    source = (ROOT / "pipeline" / "orchestrator.py").read_text()
    assert source.count("_analyze_downloaded(downloaded)") == 2, "both session paths must use the shared helper"
    namespace: dict = {}
    helper = source[source.index("def _analyze_one_source"):source.index("def _process_clips_session")]
    failures: list[str] = []

    def analyze_session(path: str) -> dict:
        time.sleep(0.2)
        if "bad" in path:
            raise RuntimeError("boom")
        return {"echo": path}

    namespace.update(
        analyze_session=analyze_session, ThreadPoolExecutor=__import__("concurrent.futures", fromlist=["x"]).ThreadPoolExecutor,
        logger=types.SimpleNamespace(exception=lambda *a, **k: None), os=os, _ANALYSIS_WORKERS=4,
        record_failure=lambda file_id: failures.append(file_id) or True, mark_as_processed=lambda *_: None)
    exec(helper, namespace)
    items = [{"path": f"/nonexistent/{n}.mp4", "meta": {"id": n, "name": f"{n}.mp4"}} for n in ("a", "bad", "c", "d")]
    start = time.monotonic()
    out = namespace["_analyze_downloaded"](items)
    elapsed = time.monotonic() - start
    assert [r["meta"]["id"] for r in out] == ["a", "c", "d"], out
    assert failures == ["bad"], failures
    assert elapsed < 0.6, f"4 sources x 0.2s should overlap, took {elapsed:.2f}s"
    namespace["_ANALYSIS_WORKERS"] = 1
    start = time.monotonic()
    namespace["_analyze_downloaded"](items)
    assert time.monotonic() - start >= 0.75, "ANALYSIS_WORKERS=1 must stay serial"


def test_selector_capture_is_isolated_per_thread() -> None:
    _stub_modules()
    import pipeline.selector_candidate_runtime as runtime
    import pipeline.stages.analyzer as analyzer
    seen: dict[str, list[str]] = {"a": [], "b": []}
    barrier = threading.Barrier(2)

    def original_analyze(path: str) -> dict:
        barrier.wait(timeout=5)               # both threads are inside analysis at the same time
        text = analyzer._parse_session(json.dumps({"activity": path, "persons": []}))
        return {"echo": path, "activity": text["activity"]}

    saved = (analyzer.analyze_session, analyzer._parse_session)
    analyzer.analyze_session = original_analyze
    analyzer._parse_session = lambda raw: json.loads(raw)
    runtime.install_flag_reset = getattr(analyzer, "_sportreel_selector_candidate_runtime_installed", False)
    if hasattr(analyzer, "_sportreel_selector_candidate_runtime_installed"):
        delattr(analyzer, "_sportreel_selector_candidate_runtime_installed")
    runtime.recover_raw_session_payload = lambda raw, _min: {"persons": [], "raw": json.loads(raw)["activity"]}
    runtime.build_selector_candidate_events = lambda persons, **k: {"candidates": [], "source": k["source_video"]}
    runtime.enrich_selector_payload = lambda payload, recovered: {**payload, "recovered": recovered["raw"]}
    runtime.dedupe_session = lambda result, **k: result
    runtime.source_duration = lambda p: 10.0
    runtime.merge_selector_payloads = lambda payloads, **k: {"payloads": payloads, "candidates": []}
    runtime._append_payload = lambda path, payload: [seen[p["recovered"]].append(p["source"]) for p in payload["payloads"]]
    try:
        runtime.install()
        threads = [threading.Thread(target=analyzer.analyze_session, args=(name,)) for name in ("a", "b")]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
    finally:
        analyzer.analyze_session, analyzer._parse_session = saved
    assert seen == {"a": ["a"], "b": ["b"]}, seen   # each thread's capture kept its own source


def test_llm_cost_calls_are_persisted_immediately() -> None:
    from integrations import llm_cost
    llm_cost.reset()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TMP_DIR"] = tmp
        try:
            usage = types.SimpleNamespace(usage_metadata=types.SimpleNamespace(
                prompt_token_count=10, candidates_token_count=2, thoughts_token_count=1, prompt_tokens_details=[]))
            llm_cost.record_call(usage, model="gemini-2.5-flash", label="t.a")
            llm_cost.record_call(usage, model="gemini-2.5-flash", label="t.b")
            rows = [json.loads(line) for line in (Path(tmp) / "pipeline-debug" / "llm_cost_calls.jsonl").read_text().splitlines()]
        finally:
            os.environ.pop("TMP_DIR", None)
    assert [r["label"] for r in rows] == ["t.a", "t.b"] and all("ts" in r for r in rows), rows


def test_stage_timer_persists_and_never_raises() -> None:
    from integrations import stage_timer
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TMP_DIR"] = tmp
        try:
            with stage_timer.timed("unit", source="x.mp4"):
                pass
            try:
                with stage_timer.timed("failing"):
                    raise ValueError("kept")
            except ValueError:
                pass
            rows = [json.loads(line) for line in (Path(tmp) / "pipeline-debug" / "stage_timings.jsonl").read_text().splitlines()]
        finally:
            os.environ.pop("TMP_DIR", None)
    assert [r["stage"] for r in rows] == ["unit", "failing"] and rows[0]["source"] == "x.mp4", rows


def test_pipeline_log_is_unbuffered_and_cache_is_wired() -> None:
    script = (ROOT / "scripts" / "run_pipeline_with_diagnostics.sh").read_text()
    assert "PYTHONUNBUFFERED=1 python -u scripts/run_tracked.py" in script
    workflow = (ROOT / ".github" / "workflows" / "pipeline-run.yml").read_text()
    assert "actions/cache/restore@v4" in workflow and "actions/cache/save@v4" in workflow
    assert "LLM_CACHE_DIR: /tmp/llm-cache" in workflow
    save = workflow[workflow.index("Save LLM analysis cache"):]
    assert "if: always()" in save.split("Upload pipeline diagnostics")[0]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS cost/time optimizations contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Contract: analyzer._parse_session/_parse_analysis extract optional phase-time
fields (setup_start/peak_time/outcome_end) for PQ-007, and pipeline.window_policy
actually consumes what analyzer produces end-to-end.

Regression target: pipeline.window_policy.resolve_window() already implements the
setup/peak/outcome phase model, but pipeline/stages/analyzer.py never requested or
extracted these fields from Gemini output at all -- every non-surf event fell into
resolve_window's naive `cap_no_phase` branch, the exact behavior PQ-007 exists to fix.
"""
from __future__ import annotations

import json
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


def _session_event(**extra) -> str:
    event = {"type": "goal", "start": 10, "end": 20, "score": 8, "description": "x", **extra}
    return json.dumps({"activity": "football", "persons": [{"id": "p1", "description": "player", "events": [event]}]})


def _single_event(**extra) -> str:
    event = {"type": "goal", "start": 10, "end": 20, "score": 8, "description": "x", **extra}
    return json.dumps({"activity": "football", "events": [event]})


def main() -> int:
    prompt_text = (ROOT / "pipeline/stages/analyzer.py").read_text(encoding="utf-8")
    for token in ["setup_start", "peak_time", "outcome_end", "_optional_phase_time"]:
        if token not in prompt_text:
            raise SystemExit(f"analyzer.py missing PQ-007 phase-time token: {token}")
    if "OPTIONAL" not in prompt_text.split("setup_start:", 1)[1][:20]:
        raise SystemExit("setup_start prompt instruction must be marked optional (best-effort, not required)")

    _install_import_stubs()
    import pipeline.stages.analyzer as analyzer

    # Fields present and numeric -> parsed through as floats.
    parsed = analyzer._parse_session(_session_event(setup_start=11, peak_time=15, outcome_end=18))
    event = parsed["persons"][0]["events"][0]
    if event.get("setup_start") != 11.0 or event.get("peak_time") != 15.0 or event.get("outcome_end") != 18.0:
        raise SystemExit(f"_parse_session did not extract phase-time fields correctly: {event}")

    # Fields absent -> None, not 0.0 (resolve_window treats None as "not provided";
    # defaulting to 0 would be a false claim of a real timestamp at second 0).
    parsed = analyzer._parse_session(_session_event())
    event = parsed["persons"][0]["events"][0]
    if event.get("setup_start") is not None or event.get("peak_time") is not None or event.get("outcome_end") is not None:
        raise SystemExit(f"_parse_session must leave phase-time fields as None when Gemini omits them: {event}")

    # Invalid/non-numeric value -> None, not a crash.
    parsed = analyzer._parse_session(_session_event(peak_time="not-a-number"))
    event = parsed["persons"][0]["events"][0]
    if event.get("peak_time") is not None:
        raise SystemExit("_parse_session must treat an invalid phase-time value as absent, not raise or default")

    # _parse_analysis (single-person path) mirrors the same extraction.
    parsed = analyzer._parse_analysis(_single_event(setup_start=11, peak_time=15, outcome_end=18))
    event = parsed["events"][0]
    if event.get("setup_start") != 11.0 or event.get("peak_time") != 15.0 or event.get("outcome_end") != 18.0:
        raise SystemExit(f"_parse_analysis did not extract phase-time fields correctly: {event}")

    # End-to-end: what analyzer produces, window_policy actually consumes.
    from pipeline.window_policy import resolve_window
    parsed = analyzer._parse_session(_session_event(start=10, end=17, setup_start=10.5, peak_time=12.0, outcome_end=13.5))
    event = parsed["persons"][0]["events"][0]
    resolved = resolve_window(event, source_duration=60)
    if resolved is None:
        raise SystemExit("analyzer-produced event with phase-time fields failed to resolve a window")
    if resolved["peak_time"] != 12.0 or resolved["outcome_end"] != 13.5:
        raise SystemExit("resolve_window did not consume analyzer-produced phase-time fields")

    print("Analyzer phase-time contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

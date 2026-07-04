#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing: {missing}")


def _install_import_stubs() -> None:
    sys.modules["config"] = types.SimpleNamespace(
        GEMINI_MODEL="test-model",
        TMP_DIR="/tmp",
        MIN_EVENT_SEC=5,
        QA_DUR_OK_MIN=1,
        QA_DUR_OK_MAX=120,
        QA_ENGAGEMENT_THRESHOLD=50,
    )
    sys.modules["langsmith"] = types.SimpleNamespace(traceable=lambda *a, **k: (lambda fn: fn))
    sys.modules["integrations.gemini"] = types.SimpleNamespace(
        genai=types.SimpleNamespace(upload_file=lambda *a, **k: None, delete_file=lambda *a, **k: None),
        upload_video=lambda *a, **k: None,
        delete_video=lambda *a, **k: None,
    )
    sys.modules["integrations.ffmpeg"] = types.SimpleNamespace(
        get_reel_specs=lambda _path: {"aspect": 9 / 16, "duration": 30, "height": 1920, "width": 1080, "has_audio": True}
    )


def _session_json(score: int) -> str:
    return json.dumps({
        "activity": "surfing",
        "session_peak": score,
        "persons": [{
            "id": "person_A",
            "description": "surfer on red board",
            "events": [{
                "type": "cutback",
                "start": 10.0,
                "end": 18.0,
                "score": score,
                "description": "candidate moment",
                "crop_x": 0.5,
                "crop_y": 0.65,
            }],
        }],
    })


def _single_json(score: int) -> str:
    return json.dumps({
        "activity": "surfing",
        "events": [{
            "type": "cutback",
            "start": 10.0,
            "end": 18.0,
            "score": score,
            "description": "candidate moment",
            "crop_x": 0.5,
            "crop_y": 0.65,
        }],
    })


def main() -> int:
    guard = _read("pipeline/analyzer_score_guard.py")
    runner = _read("scripts/run_tracked.py")
    workflow = _read(".github/workflows/operator-smoke-check.yml")
    for text in (guard, runner, workflow, _read("scripts/test_analyzer_score_guard_contract.py")):
        ast.parse(text)

    _require("guard", guard, [
        "MIN_SCORE = 6",
        "def filter_session_result",
        "def filter_single_result",
        "analyzer._parse_session = parse_session_with_score_policy",
        "analyzer._parse_analysis = parse_analysis_with_score_policy",
    ])
    _require("runner", runner, [
        "def _install_analyzer_score_guard_runtime()",
        "from pipeline.analyzer_score_guard import install",
        "_install_analyzer_score_guard_runtime()",
        "import pipeline.orchestrator as _orchestrator",
    ])
    _require("workflow", workflow, [
        "pipeline/analyzer_score_guard.py",
        "scripts/test_analyzer_score_guard_contract.py",
        "Validate Analyzer score guard contract",
    ])

    _install_import_stubs()
    import pipeline.analyzer_score_guard as guard_module
    import pipeline.stages.analyzer as analyzer
    guard_module.install()

    score5 = analyzer._parse_session(_session_json(5))
    if score5.get("persons"):
        raise SystemExit("score 5 session event must not produce a normal person/event")

    score6 = analyzer._parse_session(_session_json(6))
    if len(score6.get("persons", [])) != 1 or score6["persons"][0]["events"][0]["score"] != 6:
        raise SystemExit("score 6 session event should still pass")

    legacy5 = analyzer._parse_analysis(_single_json(5))
    if legacy5.get("events"):
        raise SystemExit("score 5 legacy event must not pass")

    legacy6 = analyzer._parse_analysis(_single_json(6))
    if len(legacy6.get("events", [])) != 1 or legacy6["events"][0]["score"] != 6:
        raise SystemExit("score 6 legacy event should still pass")

    print("Analyzer score guard contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

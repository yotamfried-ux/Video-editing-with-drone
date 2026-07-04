#!/usr/bin/env python3
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


def _session(rating: int) -> str:
    return json.dumps({"activity": "surfing", "persons": [{"id": "p1", "description": "surfer", "events": [{"type": "cutback", "start": 10, "end": 18, "score": rating, "description": "x"}]}]})


def _single(rating: int) -> str:
    return json.dumps({"activity": "surfing", "events": [{"type": "cutback", "start": 10, "end": 18, "score": rating, "description": "x"}]})


def main() -> int:
    guard_text = (ROOT / "pipeline/analyzer_score_guard.py").read_text(encoding="utf-8")
    boot_text = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    if "MIN_SCORE = 6" not in guard_text or "_install_analyzer_score_guard" not in boot_text:
        raise SystemExit("missing PQ006 guard or bootstrap")

    _install_import_stubs()
    import pipeline.analyzer_score_guard as guard
    import pipeline.stages.analyzer as analyzer
    guard.install()

    if analyzer._parse_session(_session(5)).get("persons"):
        raise SystemExit("low session rating passed")
    if not analyzer._parse_session(_session(6)).get("persons"):
        raise SystemExit("minimum valid session rating was dropped")
    if analyzer._parse_analysis(_single(5)).get("events"):
        raise SystemExit("low single rating passed")
    if not analyzer._parse_analysis(_single(6)).get("events"):
        raise SystemExit("minimum valid single rating was dropped")

    print("PQ006 contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

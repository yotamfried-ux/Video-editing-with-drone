#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def install_test_modules() -> None:
    sys.modules["config"] = types.SimpleNamespace(GEMINI_MODEL="test-model")
    sys.modules["langsmith"] = types.SimpleNamespace(traceable=lambda *a, **k: (lambda fn: fn))
    sys.modules["integrations.gemini"] = types.SimpleNamespace(
        genai=types.SimpleNamespace(upload_file=lambda *a, **k: None, delete_file=lambda *a, **k: None)
    )


def clip(idx: int, pid: str, event: dict) -> dict:
    return {
        "path": f"clip_{idx}.mp4",
        "analysis": {"persons": [{"id": pid, "description": f"athlete {pid}", "events": [event]}]},
    }


def main() -> int:
    runtime = _read("scripts/run_tracked.py")
    failsafe = _read("pipeline/identity_failsafe.py")
    for text in (runtime, failsafe, _read("scripts/test_identity_failsafe_contract.py")):
        ast.parse(text)

    require_tokens("run_tracked identity install", runtime, [
        "def _install_identity_failsafe_runtime()",
        "from pipeline.identity_failsafe import install",
        "_install_identity_failsafe_runtime()\n\nimport pipeline.orchestrator as _orchestrator",
    ])
    require_tokens("identity failsafe guard", failsafe, [
        "def _cluster_has_perception_evidence",
        "medium confidence without bbox perception evidence",
        "missing thumbnails for identity verification",
        "identity verifier error",
        "_sportreel_identity_failsafe_installed",
        "identity.genai.upload_file",
    ])

    install_test_modules()
    import pipeline.identity_failsafe as failsafe_module
    import pipeline.stages.identity as identity
    importlib.reload(failsafe_module)
    failsafe_module.install()

    event = {"type": "snap", "score": 8, "start": 1.0, "end": 6.0}
    model_data = {"clusters": [{"description": "similar athletes", "confidence": "medium", "appearances": [
        {"clip_index": 0, "person_id": "p1"}, {"clip_index": 1, "person_id": "p2"}
    ]}]}
    clusters = identity._build_clusters_from_data(model_data, [clip(0, "p1", event), clip(1, "p2", event)])
    if len(clusters) != 2 or any(len(c["appearances"]) != 1 for c in clusters):
        raise SystemExit("medium confidence without bbox evidence must split")

    bbox_event = {**event, "bbox_xyxy": [10, 20, 30, 60], "visible_ratio": 1.0, "perception_crop_usable": True}
    clusters = identity._build_clusters_from_data(model_data, [clip(0, "p1", bbox_event), clip(1, "p2", bbox_event)])
    if len(clusters) != 1:
        raise SystemExit("medium confidence with bbox evidence should reach visual verification")
    split = identity._verify_multi_clusters(clusters)
    if len(split) != 2:
        raise SystemExit("missing thumbnails must split multi-appearance cluster fail-safe")

    print("Identity failsafe contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


def require_before(label: str, text: str, first: str, second: str) -> None:
    if text.index(first) > text.index(second):
        raise SystemExit(f"{label}: expected {first!r} before {second!r}")


def main() -> int:
    runtime = _read("pipeline/runtime_quality.py")
    run_tracked = _read("scripts/run_tracked.py")
    workflow = _read(".github/workflows/operator-smoke-check.yml")

    ast.parse(runtime)
    ast.parse(run_tracked)

    require_tokens(
        "runtime quality hardening",
        runtime,
        [
            "_MIN_KEEP_SCORE = 6",
            "if _score(ev) >= _MIN_KEEP_SCORE",
            "identity_thumb_",
            "crop_x",
            "crop_y",
            "crop=640:640",
            "original = analyzer.analyze_session",
            "analyzer.analyze_session = hardened_analyze_session",
            "_sportreel_quality_runtime_installed",
        ],
    )
    require_no_tokens(
        "runtime quality hardening",
        runtime,
        [
            "best_score >= 5",
            "score >= 5",
            "include their top 2",
        ],
    )

    require_tokens(
        "tracked runner quality install",
        run_tracked,
        [
            "def _install_pipeline_quality_runtime()",
            "from pipeline.runtime_quality import install",
            "_install_pipeline_quality_runtime()",
            "import pipeline.orchestrator as _orchestrator",
        ],
    )
    require_before(
        "tracked runner quality install order",
        run_tracked,
        "_install_pipeline_quality_runtime()",
        "import pipeline.orchestrator as _orchestrator",
    )

    require_tokens(
        "operator smoke workflow quality coverage",
        workflow,
        [
            "pipeline/runtime_quality.py",
            "pipeline/stages/analyzer.py",
            "pipeline/stages/identity.py",
            "scripts/test_pipeline_quality_contract.py",
            "Validate Pipeline quality contract",
        ],
    )

    print("Pipeline quality hardening contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

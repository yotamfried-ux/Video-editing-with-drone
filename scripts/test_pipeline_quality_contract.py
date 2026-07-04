#!/usr/bin/env python3
from __future__ import annotations

import ast
import subprocess
import sys
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


def run_identity_runtime_contract() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/test_identity_failsafe_contract.py")],
        check=True,
    )


def main() -> int:
    runtime = _read("pipeline/runtime_quality.py")
    identity_failsafe = _read("pipeline/identity_failsafe.py")
    run_tracked = _read("scripts/run_tracked.py")
    workflow = _read(".github/workflows/operator-smoke-check.yml")

    ast.parse(runtime)
    ast.parse(identity_failsafe)
    ast.parse(run_tracked)

    require_tokens(
        "runtime quality hardening",
        runtime,
        [
            "_MIN_KEEP_SCORE = 6",
            "if _score(ev) >= _MIN_KEEP_SCORE",
            "_IDENTITY_THUMB_SIZE = 640",
            "identity_thumb_",
            "crop_x",
            "crop_y",
            "crop={_IDENTITY_THUMB_SIZE}:{_IDENTITY_THUMB_SIZE}:",
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
        "identity failsafe hardening",
        identity_failsafe,
        [
            "def _cluster_has_perception_evidence",
            "medium confidence without bbox perception evidence",
            "missing thumbnails for identity verification",
            "identity verifier error",
            "_sportreel_identity_failsafe_installed",
            "identity._build_clusters_from_data = _wrap_build_clusters(identity)",
            "identity._verify_multi_clusters = _wrap_verify_multi_clusters(identity)",
        ],
    )
    require_no_tokens(
        "identity failsafe hardening",
        identity_failsafe,
        [
            "keeping as-is",
            "verified.append(cluster)\n            continue\n\n            uploaded: list = []",
        ],
    )

    require_tokens(
        "tracked runner quality install",
        run_tracked,
        [
            "def _install_pipeline_quality_runtime()",
            "from pipeline.runtime_quality import install",
            "def _install_identity_failsafe_runtime()",
            "from pipeline.identity_failsafe import install",
            "_install_pipeline_quality_runtime()",
            "_install_identity_failsafe_runtime()\n\nimport pipeline.orchestrator as _orchestrator",
        ],
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

    run_identity_runtime_contract()
    print("Pipeline quality hardening contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

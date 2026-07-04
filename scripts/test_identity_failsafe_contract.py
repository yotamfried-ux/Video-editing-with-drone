#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing: {missing}")


def main() -> int:
    runner = read("scripts/run_tracked.py")
    guard = read("pipeline/identity_failsafe.py")
    for text in (runner, guard, read("scripts/test_identity_failsafe_contract.py")):
        ast.parse(text)

    require("runner", runner, [
        "def _install_identity_failsafe_runtime()",
        "from pipeline.identity_failsafe import install",
        "_install_identity_failsafe_runtime()",
        "import pipeline.orchestrator as _orchestrator",
    ])
    require("guard", guard, [
        "def _cluster_has_perception_evidence",
        "medium confidence without bbox perception evidence",
        "missing thumbnails for identity verification",
        "identity verifier error",
        "_sportreel_identity_failsafe_installed",
    ])
    if "keeping as-is" in guard:
        raise SystemExit("identity guard is fail-open")

    print("Identity failsafe contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

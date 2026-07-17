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
    bootstrap = read("pipeline/bootstrap.py")
    guard = read("pipeline/identity_failsafe.py")
    for text in (runner, bootstrap, guard, read("scripts/test_identity_failsafe_contract.py")):
        ast.parse(text)

    require("runner", runner, [
        "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
        "install_pre_orchestrator_patches()",
        "import pipeline.orchestrator as _orchestrator",
        "install_post_orchestrator_patches()",
    ])
    require("bootstrap", bootstrap, ["pipeline.identity_failsafe"])
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

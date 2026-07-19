#!/usr/bin/env python3
"""Regression: post-run business failures must replace stale succeeded status."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/record_publishable_business_gate_status.py"
DIAGNOSTICS_PATH = ROOT / "scripts/run_pipeline_with_diagnostics.sh"


def load_module():
    spec = importlib.util.spec_from_file_location("publishable_gate_status", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load gate status propagation module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module()
    calls: list[dict] = []

    changed = module.record_gate_failure(
        {
            "passed": False,
            "errors": [
                "athlete_A: eligible athlete has no primary publishable reel",
                "athlete_B: part 1 did not pass final QA",
            ],
        },
        result_path="/tmp/pipeline-debug/publishable_reel_gate_result.json",
        marker=lambda **fields: calls.append(fields),
        reader=lambda: {"status": "failed", "stage": "publishable_business_gate_failed"},
    )
    if not changed or len(calls) != 1:
        raise SystemExit(f"failed business gate did not emit one terminal status update: {calls}")
    fields = calls[0]
    expected = {
        "status": "failed",
        "stage": "publishable_business_gate_failed",
        "progress": 1.0,
        "failure_source": "publishable_reel_business_gate",
        "publishable_gate_error_count": 2,
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            raise SystemExit(f"terminal status field {key} must be {value!r}, got {fields.get(key)!r}")
    if "no primary publishable reel" not in fields.get("error", ""):
        raise SystemExit("operator-facing terminal error lost the business-gate reason")

    calls.clear()
    changed = module.record_gate_failure(
        {"passed": True, "errors": []},
        result_path="/tmp/passed.json",
        marker=lambda **fields: calls.append(fields),
    )
    if changed or calls:
        raise SystemExit("passing business gate must not rewrite the terminal run status")

    diagnostics = DIAGNOSTICS_PATH.read_text(encoding="utf-8")
    required = [
        'if [ "$STATUS" -eq 0 ] && [ "$BUSINESS_GATE_STATUS" -ne 0 ]; then',
        'python scripts/record_publishable_business_gate_status.py "$PUBLISHABLE_GATE_RESULT_FILE"',
        'exit "$BUSINESS_GATE_STATUS"',
    ]
    missing = [token for token in required if token not in diagnostics]
    if missing:
        raise SystemExit(f"production diagnostics missing status propagation: {missing}")
    if diagnostics.index("record_publishable_business_gate_status.py") > diagnostics.index('exit "$BUSINESS_GATE_STATUS"'):
        raise SystemExit("operator status must be corrected before the workflow exits")

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    required_source = [
        "from integrations.run_status import mark_terminal_run_strict, read_terminal_state",
        "write_status_outbox",
        "verify_terminal_state",
        '"stage": "publishable_business_gate_failed"',
        '"status": "failed"',
        '"failure_source": "publishable_reel_business_gate"',
    ]
    missing = [token for token in required_source if token not in source]
    if missing:
        raise SystemExit(f"status propagation script missing contract tokens: {missing}")

    print("Publishable business gate status propagation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

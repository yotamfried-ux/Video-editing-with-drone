#!/usr/bin/env python3
"""Propagate a post-pipeline business-gate failure to durable/operator status."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"publishable business gate result missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"publishable business gate result is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("publishable business gate result must be a JSON object")
    return payload


def record_gate_failure(
    payload: dict[str, Any],
    *,
    result_path: str,
    marker: Callable[..., None],
) -> bool:
    """Mark the run failed when the deterministic business gate did not pass."""
    if payload.get("passed") is True:
        return False
    errors = [str(error).strip() for error in payload.get("errors", []) or [] if str(error).strip()]
    if not errors:
        errors = ["publishable reel business gate failed without a detailed error"]
    summary = "; ".join(errors[:5])
    if len(errors) > 5:
        summary += f"; +{len(errors) - 5} more"
    marker(
        status="failed",
        stage="publishable_business_gate_failed",
        progress=1.0,
        error=summary[:2000],
        failure_source="publishable_reel_business_gate",
        publishable_gate_result_path=result_path,
        publishable_gate_error_count=len(errors),
        publishable_gate_errors=errors[:20],
    )
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: record_publishable_business_gate_status.py GATE_RESULT_JSON", file=sys.stderr)
        return 2
    result_path = Path(sys.argv[1])
    payload = _load(result_path)
    from integrations.run_status import mark_terminal_run

    changed = record_gate_failure(
        payload,
        result_path=str(result_path),
        marker=mark_terminal_run,
    )
    print(
        "publishable business gate failure propagated to operator status"
        if changed
        else "publishable business gate passed; terminal status unchanged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

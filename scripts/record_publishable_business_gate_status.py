#!/usr/bin/env python3
"""Propagate a post-pipeline business-gate failure with durable convergence proof."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
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


def write_status_outbox(path: Path, payload: dict[str, Any]) -> None:
    """Persist a retryable terminal-state correction when remote convergence fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": "sportreel.terminal_status_outbox.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def verify_terminal_state(actual: dict[str, Any]) -> bool:
    """Verify the durable run and global operator signal agree on business failure."""
    if not isinstance(actual, dict):
        return False
    # Tests and connector adapters may return one flattened run row.
    if "status" in actual or "stage" in actual:
        return (
            str(actual.get("status") or "") == "failed"
            and str(actual.get("stage") or "") == "publishable_business_gate_failed"
        )
    run_row = actual.get("run") if isinstance(actual.get("run"), dict) else None
    global_row = actual.get("global") if isinstance(actual.get("global"), dict) else None
    if run_row is None or global_row is None:
        return False
    global_meta = global_row.get("meta") if isinstance(global_row.get("meta"), dict) else {}
    return (
        str(run_row.get("status") or "") == "failed"
        and str(run_row.get("stage") or "") == "publishable_business_gate_failed"
        and str(global_row.get("stage") or "") == "failed"
        and str(global_meta.get("terminal_status") or "") == "failed"
    )


def record_gate_failure(
    payload: dict[str, Any],
    *,
    result_path: str,
    marker: Callable[..., None],
    reader: Callable[[], dict[str, Any]] | None = None,
    outbox_path: Path | None = None,
) -> bool:
    """Mark the run failed, read it back, and leave an outbox on any mismatch."""
    if payload.get("passed") is True:
        return False
    errors = [str(error).strip() for error in payload.get("errors", []) or [] if str(error).strip()]
    if not errors:
        errors = ["publishable reel business gate failed without a detailed error"]
    summary = "; ".join(errors[:5])
    if len(errors) > 5:
        summary += f"; +{len(errors) - 5} more"
    fields = {
        "status": "failed",
        "stage": "publishable_business_gate_failed",
        "progress": 1.0,
        "error": summary[:2000],
        "failure_source": "publishable_reel_business_gate",
        "publishable_gate_result_path": result_path,
        "publishable_gate_error_count": len(errors),
        "publishable_gate_errors": errors[:20],
    }
    outbox = outbox_path or Path(result_path).with_name("terminal_status_outbox.json")
    try:
        marker(**fields)
        actual = reader() if reader is not None else None
        if reader is not None and not verify_terminal_state(actual or {}):
            raise RuntimeError(f"terminal status read-back mismatch: {actual!r}")
    except Exception as exc:
        write_status_outbox(outbox, {
            "operation": "set_publishable_business_gate_failure",
            "pipeline_run_id": os.getenv("PIPELINE_RUN_ID") or None,
            "expected": fields,
            "result_path": result_path,
            "last_error": str(exc),
        })
        raise
    try:
        outbox.unlink()
    except FileNotFoundError:
        pass
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: record_publishable_business_gate_status.py GATE_RESULT_JSON", file=sys.stderr)
        return 2
    result_path = Path(sys.argv[1])
    payload = _load(result_path)
    from integrations.run_status import mark_terminal_run_strict, read_terminal_state

    changed = record_gate_failure(
        payload,
        result_path=str(result_path),
        marker=mark_terminal_run_strict,
        reader=read_terminal_state,
        outbox_path=result_path.with_name("terminal_status_outbox.json"),
    )
    print(
        "publishable business gate failure propagated and read back from operator status"
        if changed
        else "publishable business gate passed; terminal status unchanged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

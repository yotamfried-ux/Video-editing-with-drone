"""Durable record of where events and athletes are lost between analysis and upload.

`record("sanitize_drop", source=name, reason="shorter_than_min", ...)` appends one JSON row to
$TMP_DIR/pipeline-debug/event_funnel.jsonl, flushed immediately so it survives a killed run. The run digest
(scripts/print_run_diagnostics.py) reads it to name the stage and reason for every athlete that ended without a reel.
Never raises: diagnostics must not affect the pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(os.getenv("TMP_DIR", "/tmp/dtor"), "pipeline-debug", "event_funnel.jsonl")


def record(stage: str, **meta: Any) -> None:
    try:
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        row = {"ts": round(time.time(), 3), "stage": stage, **meta}
        with _lock, open(_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            handle.flush()
    except Exception as exc:
        logger.debug("event funnel append failed: %s", exc)

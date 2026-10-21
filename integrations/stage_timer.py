"""Durable per-stage wall-clock timing.

`with timed("analyze", source=name):` prints one line and appends a JSON record to
$TMP_DIR/pipeline-debug/stage_timings.jsonl immediately (flushed), so timing survives a killed run.
Never raises: timing must not affect the pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(os.getenv("TMP_DIR", "/tmp/dtor"), "pipeline-debug", "stage_timings.jsonl")


def record(stage: str, seconds: float, **meta: Any) -> None:
    try:
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        row = {"ts": round(time.time(), 3), "stage": stage, "seconds": round(seconds, 3), **meta}
        with _lock, open(_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            handle.flush()
    except Exception as exc:
        logger.debug("stage timing append failed: %s", exc)


@contextmanager
def timed(stage: str, **meta: Any) -> Iterator[None]:
    start = time.monotonic()
    try:
        yield
    finally:
        seconds = time.monotonic() - start
        detail = " ".join(f"{k}={str(v)[:60]}" for k, v in meta.items())
        print(f"⏱️  {stage} took {seconds:.1f}s {detail}".rstrip(), flush=True)
        record(stage, seconds, **meta)

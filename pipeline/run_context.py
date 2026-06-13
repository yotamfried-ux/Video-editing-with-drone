"""
pipeline/run_context.py — per-run correlation id.

A single RUN_ID is generated once at the start of a pipeline run and threaded
through pipeline_status meta, the qa_results.jsonl / quality_issues.jsonl
artifacts, Sentry scope, and logs — so all evidence from one run is correlated.
Import-light (stdlib only).
"""

from uuid import uuid4

_run_id: str = ""


def new_run_id() -> str:
    """Generate and store a fresh run id for this process. Returns it."""
    global _run_id
    _run_id = uuid4().hex[:12]
    return _run_id


def get_run_id() -> str:
    """Return the current run id (empty string if none started yet)."""
    return _run_id

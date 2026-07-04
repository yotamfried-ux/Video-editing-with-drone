"""Tracked Phase 1 entry point for GitHub Actions."""

import os
import sys

# When executed as `python scripts/run_tracked.py`, Python puts `scripts/` on
# sys.path instead of the repository root. Add the root so top-level packages
# such as `integrations` and `pipeline` import reliably in GitHub Actions.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.run_status import mark_run, mark_terminal_run


_NO_DRAFTS_ERROR = "Pipeline completed without REVIEW drafts."
_produced_review_drafts = False
_last_observed_stage = "starting"
_last_observed_progress = 0.01
_last_observed_meta: dict = {}


def _install_status_mirror() -> None:
    """Mirror singleton live progress into the active durable run row."""
    try:
        import integrations.supabase_uploader as status_writer
    except Exception:
        return

    original = status_writer.write_pipeline_status

    def tracked_write_pipeline_status(stage: str, progress: float, **meta) -> None:
        global _produced_review_drafts, _last_observed_stage, _last_observed_progress, _last_observed_meta
        original(stage, progress, **meta)
        _last_observed_stage = stage
        _last_observed_progress = progress
        _last_observed_meta = dict(meta)
        mark_run(stage=stage, progress=progress, meta=meta)
        if stage == "done" and int(meta.get("drafts_created") or 0) > 0:
            _produced_review_drafts = True

    status_writer.write_pipeline_status = tracked_write_pipeline_status


def _no_drafts_failure() -> tuple[str, str, dict]:
    if _last_observed_stage == "qa":
        reason = "all_draft_uploads_failed"
        error = "All draft uploads failed after QA; no REVIEW drafts were created."
    else:
        reason = f"no_drafts_after_{_last_observed_stage}"
        error = f"{_NO_DRAFTS_ERROR} Last observed stage: {_last_observed_stage}."
    meta = {
        "error_code": reason,
        "no_drafts_reason": reason,
        "last_observed_stage": _last_observed_stage,
        "last_observed_progress": _last_observed_progress,
        "last_observed_meta": _last_observed_meta,
    }
    return reason, error, meta


mark_run(status="running", stage="starting", progress=0.01)
_install_status_mirror()

import pipeline.orchestrator as _orchestrator
from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    try:
        main()
    except Exception as exc:
        mark_terminal_run(status="failed", stage="failed", error=str(exc))
        raise

    if _orchestrator.no_input:
        mark_terminal_run(status="no_input", stage="no_input", progress=1.0)
    elif _produced_review_drafts:
        mark_terminal_run(status="succeeded", stage="finished", progress=1.0)
    else:
        stage, error, meta = _no_drafts_failure()
        mark_terminal_run(status="failed", stage=stage, error=error, **meta)
        sys.exit(1)

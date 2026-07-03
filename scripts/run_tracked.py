"""Tracked Phase 1 entry point for GitHub Actions."""

import os
import sys

# When executed as `python scripts/run_tracked.py`, Python puts `scripts/` on
# sys.path instead of the repository root. Add the root so top-level packages
# such as `integrations` and `pipeline` import reliably in GitHub Actions.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.run_status import mark_run, mark_terminal_run


def _install_status_mirror() -> None:
    """Mirror singleton live progress into the active durable run row.

    The pipeline still writes `pipeline_status` for the global live progress bar,
    but app-triggered actions need their own durable row to explain what happened
    to that specific run. This wrapper is installed before importing the
    orchestrator so every `write_pipeline_status(...)` import used by the run is
    mirrored to `pipeline_runs` when PIPELINE_RUN_ID is present.
    """
    try:
        import integrations.supabase_uploader as status_writer
    except Exception:
        return

    original = status_writer.write_pipeline_status

    def tracked_write_pipeline_status(stage: str, progress: float, **meta) -> None:
        original(stage, progress, **meta)
        mark_run(stage=stage, progress=progress, meta=meta)

    status_writer.write_pipeline_status = tracked_write_pipeline_status


mark_run(status="running", stage="starting", progress=0.01)
_install_status_mirror()

import pipeline.orchestrator as _orchestrator
from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    ok = False
    try:
        main()
        ok = True
    finally:
        if ok:
            # no_input=True means the orchestrator found nothing to do (no new videos).
            # Don't overwrite that with succeeded — succeeded implies drafts were produced.
            if _orchestrator.no_input:
                mark_terminal_run(status="no_input", stage="no_input", progress=1.0)
            else:
                mark_terminal_run(status="succeeded", stage="finished", progress=1.0)
        else:
            mark_terminal_run(status="failed", stage="failed")

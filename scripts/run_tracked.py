"""Tracked Phase 1 entry point for GitHub Actions."""
from integrations.run_status import mark_run

mark_run(status="running", stage="starting", progress=0.01)

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
            mark_run(status="succeeded", stage="finished", progress=1.0)
        else:
            mark_run(status="failed", stage="failed")

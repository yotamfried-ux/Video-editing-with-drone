"""run.py — D to R pipeline Phase 1 entry point."""
from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    from pipeline.preflight import run_preflight_checks
    init_sentry()
    run_preflight_checks()
    main()

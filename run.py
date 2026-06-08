"""run.py — D to R pipeline Phase 1 entry point."""
from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    main()

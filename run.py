"""run.py — D to R pipeline Phase 1 entry point."""
from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches

install_pre_orchestrator_patches()

import pipeline.orchestrator as _orchestrator  # noqa: F401  (import must precede post-patches)

install_post_orchestrator_patches()

from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    main()

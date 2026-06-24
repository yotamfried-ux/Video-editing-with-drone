"""run_surf.py — Phase 1 entry point with surf-specific editing policy enabled."""
from pipeline import enable_surf_editor_policy

# Must run before importing orchestrator, because orchestrator imports editor symbols.
enable_surf_editor_policy()

from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    main()

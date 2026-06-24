"""Interpreter bootstrap for the production pipeline entrypoint.

Python imports ``sitecustomize`` automatically when it is present on sys.path.
We use it narrowly: only ``python run.py`` enables the surf editor policy, before
``run.py`` imports ``pipeline.orchestrator`` and before orchestrator captures
editor symbols. Unit tests and helper scripts keep their normal import behavior.
"""

from __future__ import annotations

from pathlib import Path
import sys


if Path(sys.argv[0]).name == "run.py":
    try:
        from pipeline import enable_surf_editor_policy

        enable_surf_editor_policy()
    except Exception:
        # Never make Python startup fail before the real pipeline logger/Sentry
        # are initialized. The normal editor remains available as a safe fallback.
        pass

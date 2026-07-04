"""Bootstrap guards for script entrypoints.

Python imports this file automatically when a script in this directory is run.
Keep it narrow and fail-safe.
"""
from __future__ import annotations

from pathlib import Path
import sys


def _install_analyzer_score_guard() -> None:
    root = Path(__file__).resolve().parents[1]
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from pipeline.analyzer_score_guard import install
        install()
    except Exception:
        # Do not fail interpreter startup. The dedicated contract test verifies
        # this hook and the normal pipeline logging will surface later failures.
        pass


_install_analyzer_score_guard()

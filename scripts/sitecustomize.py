"""Bootstrap guards for script entrypoints.

Python imports this file automatically when a script in this directory is run.
Keep it narrow and fail-safe.
"""
from __future__ import annotations

from pathlib import Path
import sys


def _repo_root() -> str:
    root = Path(__file__).resolve().parents[1]
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root_text


def _install_analyzer_score_guard() -> None:
    _repo_root()
    try:
        from pipeline.analyzer_score_guard import install
        install()
    except Exception:
        pass


def _install_window_policy() -> None:
    _repo_root()
    try:
        from pipeline.window_policy import install
        install()
    except Exception:
        pass


def _install_narrative_policy() -> None:
    _repo_root()
    try:
        from pipeline.narrative_policy import install
        install()
    except Exception:
        pass


_install_analyzer_score_guard()
_install_window_policy()
_install_narrative_policy()

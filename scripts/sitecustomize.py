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


def _install_perception_runtime() -> None:
    _repo_root()
    try:
        from pipeline.perception.runtime import install
        install()
    except Exception:
        pass


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


def _install_cut_window_guard() -> None:
    _repo_root()
    try:
        from pipeline.cut_window_guard import install
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


def _install_qa_gate_policy() -> None:
    _repo_root()
    try:
        from pipeline.qa_gate_policy import install
        install()
    except Exception:
        pass


def _install_draft_diagnostics() -> None:
    _repo_root()
    try:
        from pipeline.draft_diagnostics import install
        install()
    except Exception:
        pass


def _install_candidate_ledger() -> None:
    _repo_root()
    try:
        from pipeline.candidate_ledger import install
        install()
    except Exception:
        pass


def _install_athlete_canonicalization() -> None:
    _repo_root()
    try:
        from pipeline.athlete_canonicalization import install
        install()
    except Exception:
        pass


def _install_real_identity_gate() -> None:
    _repo_root()
    try:
        from pipeline.real_identity_gate import install
        install()
    except Exception:
        pass


def _install_final_duplicate_guard() -> None:
    _repo_root()
    try:
        from pipeline.final_duplicate_guard import install
        install()
    except Exception:
        pass


def _install_context_qa_gate() -> None:
    _repo_root()
    try:
        from pipeline.context_qa_gate import install
        install()
    except Exception:
        pass


def _install_context_qa_long_video() -> None:
    _repo_root()
    try:
        from pipeline.context_qa_long_video import install
        install()
    except Exception:
        pass


_install_perception_runtime()
_install_analyzer_score_guard()
_install_window_policy()
_install_cut_window_guard()
_install_narrative_policy()
_install_qa_gate_policy()
_install_draft_diagnostics()
_install_candidate_ledger()
_install_athlete_canonicalization()
_install_real_identity_gate()
_install_final_duplicate_guard()
_install_context_qa_gate()
_install_context_qa_long_video()

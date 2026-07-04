"""Interpreter bootstrap for production pipeline entrypoints.

Python imports ``sitecustomize`` automatically when it is present on sys.path.
Keep this file narrow: only process-wide safety guards that must run before
pipeline modules capture imported symbols belong here.
"""

from __future__ import annotations

from pathlib import Path
import os
import sys


def _enable_surf_editor_policy() -> None:
    if Path(sys.argv[0]).name != "run.py":
        return
    try:
        from pipeline import enable_surf_editor_policy
        enable_surf_editor_policy()
    except Exception:
        # Never make Python startup fail before the real pipeline logger/Sentry
        # are initialized. The normal editor remains available as a safe fallback.
        pass


def _install_r2_batch_scope() -> None:
    backend = (os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive")
    batch_id = (os.getenv("RAW_BATCH_ID") or os.getenv("BATCH_ID") or "").strip()
    if backend != "r2" or not batch_id:
        return
    try:
        from pipeline.r2_batch_scope import install
        install()
    except Exception:
        # Avoid failing interpreter startup; storage preflight / pipeline execution
        # will surface actionable errors once logging is initialized.
        pass


_enable_surf_editor_policy()
_install_r2_batch_scope()

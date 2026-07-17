"""Scope temporary editor-to-QA state beyond human-readable athlete labels."""
from __future__ import annotations

import re
import threading
from typing import Any

_INSTALLED_FLAG = "_sportreel_publishable_pending_scope_installed"


def _normal(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def install() -> None:
    """Include the worker identity in transient publishable state keys.

    The current orchestrator processes athlete clusters sequentially, but this prevents
    a future concurrent renderer from overwriting another athlete with the same model
    description before its QA gate consumes pending lineage and variant failures.
    """
    import pipeline.publishable_reel_policy as policy

    if getattr(policy, _INSTALLED_FLAG, False):
        return

    def scoped_pending_key(sport: str, athlete_label: str) -> str:
        return (
            f"thread_{threading.get_ident()}::"
            f"{_normal(sport)}::{_normal(athlete_label)}"
        )

    policy._pending_key = scoped_pending_key
    setattr(policy, _INSTALLED_FLAG, True)

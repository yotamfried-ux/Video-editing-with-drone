"""Scope temporary editor-to-QA state by an invocation-unique token."""
from __future__ import annotations

import contextvars
import re
import threading
import uuid
from collections import deque
from typing import Any

_INSTALLED_FLAG = "_sportreel_publishable_pending_scope_installed"
_PENDING_LOCK = threading.RLock()
_PENDING_TOKENS: dict[tuple[int, str, str], deque[str]] = {}
_ACTIVE_TOKEN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sportreel_publishable_invocation_token",
    default=None,
)
_ACTIVE_IDENTITY: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "sportreel_publishable_invocation_identity",
    default=None,
)


def _normal(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _identity(sport: str, athlete_label: str) -> tuple[str, str]:
    return _normal(sport), _normal(athlete_label)


def _queue_key(sport: str, athlete_label: str) -> tuple[int, str, str]:
    normalized_sport, normalized_label = _identity(sport, athlete_label)
    return threading.get_ident(), normalized_sport, normalized_label


def current_scope_token(*, required: bool = False) -> str | None:
    """Return the active render-to-QA invocation token for this execution context."""
    token = _ACTIVE_TOKEN.get()
    if required and not token:
        raise RuntimeError("publishable QA invocation scope is not active")
    return token


def create_pending_scope(sport: str, athlete_label: str) -> str:
    """Create and enqueue one unique token after an editor invocation completes."""
    token = f"publishable_{uuid.uuid4().hex}"
    key = _queue_key(sport, athlete_label)
    with _PENDING_LOCK:
        _PENDING_TOKENS.setdefault(key, deque()).append(token)
    return token


def activate_next_scope(sport: str, athlete_label: str) -> str:
    """Activate the matching editor invocation immediately before its QA gate."""
    key = _queue_key(sport, athlete_label)
    with _PENDING_LOCK:
        queue = _PENDING_TOKENS.get(key)
        if not queue:
            raise RuntimeError(
                "publishable QA could not find a pending render invocation for "
                f"{athlete_label!r} ({sport!r})"
            )
        token = queue.popleft()
        if not queue:
            _PENDING_TOKENS.pop(key, None)
    _ACTIVE_TOKEN.set(token)
    _ACTIVE_IDENTITY.set(_identity(sport, athlete_label))
    return token


def release_scope(token: str) -> None:
    """Release only the active invocation identified by ``token``."""
    if _ACTIVE_TOKEN.get() == token:
        _ACTIVE_TOKEN.set(None)
        _ACTIVE_IDENTITY.set(None)


def pending_key(sport: str, athlete_label: str) -> str:
    """Return the active token during QA, otherwise enqueue a new render token."""
    active = _ACTIVE_TOKEN.get()
    if active and _ACTIVE_IDENTITY.get() == _identity(sport, athlete_label):
        return active
    return create_pending_scope(sport, athlete_label)


def install() -> None:
    """Replace label-derived transient keys with invocation-scoped tokens."""
    import pipeline.publishable_reel_policy as policy

    if getattr(policy, _INSTALLED_FLAG, False):
        return
    policy._pending_key = pending_key
    setattr(policy, _INSTALLED_FLAG, True)

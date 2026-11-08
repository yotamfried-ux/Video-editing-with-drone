"""Thread-safe context management for publishable reel render/QA invocations."""
from __future__ import annotations

import collections
import contextvars
import os
import threading
from collections import deque
from typing import Any

_ACTIVE_TOKEN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_sportreel_active_publishable_token", default=None
)
_ACTIVE_IDENTITY: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_sportreel_active_publishable_identity", default=None
)
_PENDING_LOCK = threading.RLock()
_PENDING_TOKENS: dict[str, deque[str]] = {}
_SCOPES_BY_INVOCATION_ID: dict[str, str] = {}
_INVOCATION_BY_TOKEN: dict[str, str] = {}
_COUNTER = 0


def _identity(sport: str, athlete_label: str) -> str:
    s = " ".join(str(sport or "sport").strip().lower().split())
    a = " ".join(str(athlete_label or "unknown athlete").strip().lower().split())
    return f"{s}::{a}"


def pending_key(sport: str, athlete_label: str, *, invocation_id: str | None = None) -> str:
    active = _ACTIVE_TOKEN.get()
    if active is not None:
        return active
    return create_pending_scope(sport, athlete_label, invocation_id=invocation_id)


def create_pending_scope(sport: str, athlete_label: str, *, invocation_id: str | None = None) -> str:
    """Register an editor invocation whose QA results will be published."""
    global _COUNTER
    ident = _identity(sport, athlete_label)
    with _PENDING_LOCK:
        _COUNTER += 1
        token = f"publishable_{ident}::{os.getpid()}::{_COUNTER}"
        if invocation_id:
            inv_str = str(invocation_id)
            _SCOPES_BY_INVOCATION_ID[inv_str] = token
            _INVOCATION_BY_TOKEN[token] = inv_str
        _PENDING_TOKENS.setdefault(ident, deque()).append(token)
    return token


def bind_invocation_id(token: str, invocation_id: str) -> None:
    """Bind a render-created token to a unique ID carried through its EDL."""
    if not token or not invocation_id:
        raise ValueError("scope token and invocation_id are required")
    with _PENDING_LOCK:
        inv_str = str(invocation_id)
        _SCOPES_BY_INVOCATION_ID[inv_str] = token
        _INVOCATION_BY_TOKEN[token] = inv_str


def discard_pending_scope(*, invocation_id: str | None = None, token: str | None = None) -> None:
    """Discard an unconsumed pending scope after a render failure or abort."""
    with _PENDING_LOCK:
        resolved_token = token
        if invocation_id:
            resolved_token = _SCOPES_BY_INVOCATION_ID.pop(str(invocation_id), resolved_token)
        if resolved_token:
            inv_str = _INVOCATION_BY_TOKEN.pop(resolved_token, None)
            if inv_str:
                _SCOPES_BY_INVOCATION_ID.pop(inv_str, None)
            for ident, q in list(_PENDING_TOKENS.items()):
                try:
                    q.remove(resolved_token)
                except ValueError:
                    pass
                if not q:
                    _PENDING_TOKENS.pop(ident, None)


def activate_next_scope(sport: str, athlete_label: str, *, invocation_id: str | None = None) -> str:
    """Activate the matching editor invocation immediately before its QA gate."""
    ident = _identity(sport, athlete_label)
    with _PENDING_LOCK:
        token: str | None = None
        if invocation_id and str(invocation_id) in _SCOPES_BY_INVOCATION_ID:
            token = _SCOPES_BY_INVOCATION_ID.pop(str(invocation_id))
            _INVOCATION_BY_TOKEN.pop(token, None)
            # Remove from FIFO queue as well to avoid leaks or double consumption
            for pending_key, queue in list(_PENDING_TOKENS.items()):
                try:
                    queue.remove(token)
                except ValueError:
                    pass
                if not queue:
                    _PENDING_TOKENS.pop(pending_key, None)
        else:
            queue = _PENDING_TOKENS.get(ident)
            if queue:
                token = queue.popleft()
                if not queue:
                    _PENDING_TOKENS.pop(ident, None)
                if token:
                    inv_str = _INVOCATION_BY_TOKEN.pop(token, None)
                    if inv_str:
                        _SCOPES_BY_INVOCATION_ID.pop(inv_str, None)

        if not token:
            raise RuntimeError(
                "publishable QA could not find a pending render invocation for "
                f"{athlete_label!r} ({sport!r})"
            )

        _ACTIVE_TOKEN.set(token)
        _ACTIVE_IDENTITY.set(ident)
        return token


def release_scope(token: str) -> None:
    """Release only the active invocation identified by ``token``."""
    if _ACTIVE_TOKEN.get() == token:
        _ACTIVE_TOKEN.set(None)
        _ACTIVE_IDENTITY.set(None)


def current_scope_token(*, required: bool = False) -> str | None:
    """Return the currently active publishable reel invocation token, if any."""
    tok = _ACTIVE_TOKEN.get()
    if required and tok is None:
        raise RuntimeError("No active publishable scope token in current context")
    return tok


def current_scope_identity() -> str | None:
    """Return the normalized sport::athlete identity of the active token."""
    return _ACTIVE_IDENTITY.get()


def has_active_scope() -> bool:
    """Return True when this thread is actively processing a publishable reel."""
    return _ACTIVE_TOKEN.get() is not None

_INSTALLED_FLAG = "_sportreel_publishable_pending_scope_installed"


def install() -> None:
    """Replace label-derived transient keys with invocation-scoped tokens."""
    import pipeline.publishable_reel_policy as policy

    if getattr(policy, _INSTALLED_FLAG, False):
        return
    policy._pending_key = pending_key
    setattr(policy, _INSTALLED_FLAG, True)

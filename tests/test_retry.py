"""Unit tests for integrations.retry.retry_transient."""

import pytest

from integrations.retry import retry_transient, is_transient


def test_non_transient_raises_immediately():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("totally unrelated bug")

    with pytest.raises(ValueError):
        retry_transient(fn, attempts=3, sleep=lambda s: None)
    assert calls["n"] == 1  # no retries for non-transient


def test_transient_then_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("HTTP 429 quota exceeded")
        return "ok"

    assert retry_transient(fn, attempts=5, sleep=lambda s: None) == "ok"
    assert calls["n"] == 3


def test_transient_exhausts_attempts_and_reraises():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RuntimeError("503 unavailable")

    with pytest.raises(RuntimeError):
        retry_transient(fn, attempts=3, sleep=lambda s: None)
    assert calls["n"] == 3


def test_deadline_exceeded_is_transient():
    # The marker the prior code was missing.
    assert is_transient(RuntimeError("504 DeadlineExceeded"))
    assert is_transient(RuntimeError("operation timed out"))


def test_backoff_delays_are_exponential():
    delays = []

    def fn():
        raise RuntimeError("429 rate limit")

    with pytest.raises(RuntimeError):
        retry_transient(fn, attempts=4, base_delay=4, sleep=delays.append)
    assert delays == [4, 8, 16]  # one fewer than attempts; last attempt re-raises

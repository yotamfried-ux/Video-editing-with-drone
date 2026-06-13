"""
integrations/retry.py — shared transient-error retry with exponential backoff.

Single source of truth for the backoff pattern that previously lived (duplicated)
in pipeline/stages/analyzer.py (`_with_retry`) and pipeline/stages/identity.py
(`_retry_gemini`). Pure stdlib so it is import-light and unit-testable without the
Gemini / CLIP / torch stack.
"""

import logging
import time

logger = logging.getLogger(__name__)

# Substrings (lowercased) that mark a retryable transient error. Covers Gemini
# rate/quota/availability AND deadline/timeout (DeadlineExceeded) AND Drive/
# Supabase rate-limit + transient 5xx error shapes.
DEFAULT_MARKERS: tuple[str, ...] = (
    "429", "quota", "rate", "resource exhausted",
    "500", "502", "503", "504", "unavailable", "backenderror",
    "deadline", "timeout", "timed out",
    "userratelimitexceeded",
)


def is_transient(exc: Exception, markers: tuple[str, ...] = DEFAULT_MARKERS) -> bool:
    """True when the exception's string representation matches a transient marker."""
    text = str(exc).lower()
    return any(m in text for m in markers)


def retry_transient(fn, *, attempts: int = 3, base_delay: int = 4,
                    markers: tuple[str, ...] = DEFAULT_MARKERS,
                    label: str = "call", sleep=time.sleep):
    """Call fn(); retry on transient errors with exponential backoff (base, 2x, 4x...).

    Non-transient errors raise immediately. The final attempt re-raises even if
    transient. `sleep` is injectable so tests run without real delays.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            if not is_transient(e, markers) or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(f"  ⏳ {label} transient error ({attempt}/{attempts}), retry in {delay}s...")
            logger.warning("%s transient error, retry %d/%d in %ds: %s",
                           label, attempt, attempts, delay, e)
            sleep(delay)

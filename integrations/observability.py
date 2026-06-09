"""
integrations/observability.py — optional Sentry error monitoring.

No-op unless SENTRY_DSN is set, mirroring the LANGSMITH optional-feature pattern.
Wiring is centralised: the LoggingIntegration captures every `logger.error(...)`
across the pipeline as a Sentry event (and INFO/WARNING as breadcrumbs), so the
fail-open `except` blocks surface in Sentry without per-call instrumentation.
"""

import logging

import config

logger = logging.getLogger(__name__)
_initialized = False


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is configured. Safe to call multiple times.

    Returns True if Sentry was activated, False otherwise (disabled or failure).
    Never raises — observability must not be able to crash the pipeline.
    """
    global _initialized
    if _initialized or not config.SENTRY_DSN:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=config.SENTRY_DSN,
            environment=config.SENTRY_ENVIRONMENT,
            traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[LoggingIntegration(
                level=logging.INFO,         # INFO+ become breadcrumbs
                event_level=logging.ERROR,  # ERROR+ become Sentry events
            )],
        )
        _initialized = True
        logger.info("Sentry initialized (env=%s)", config.SENTRY_ENVIRONMENT)
        return True
    except Exception as exc:  # never let observability break the pipeline
        logger.warning("Sentry init failed (continuing without it): %s", exc)
        return False

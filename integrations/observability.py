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


def setup_pipeline_scope(run_id: str, video_name: str = "", **context) -> None:
    """Tag the Sentry scope for this run so events/breadcrumbs are correlated.

    No-op (and never raises) when Sentry is not active. Filter Sentry by
    `pipeline_run_id` to see one run's errors + identity breadcrumbs together.
    """
    try:
        import sentry_sdk
        sentry_sdk.set_tag("pipeline_run_id", run_id)
        if video_name:
            sentry_sdk.set_tag("video", video_name)
        if context:
            sentry_sdk.set_context("pipeline", context)
    except Exception:
        pass


def breadcrumb(category: str, message: str, **data) -> None:
    """Add a Sentry breadcrumb (no-op if Sentry inactive). Used to record
    identity merge/split decisions so a mis-merge is debuggable after the fact."""
    try:
        import sentry_sdk
        sentry_sdk.add_breadcrumb(category=category, message=message, data=data or None)
    except Exception:
        pass


def capture(exc: Exception, **context) -> None:
    """Send an exception to Sentry without re-raising (no-op if inactive).

    For the fail-open `except` blocks: keep behavior non-blocking, but make the
    error visible instead of vanishing."""
    try:
        import sentry_sdk
        if context:
            # sentry_sdk 2.x renamed push_scope() → new_scope(); support both.
            scope_cm = getattr(sentry_sdk, "new_scope", None) or sentry_sdk.push_scope
            with scope_cm() as scope:
                for k, v in context.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass

"""deliver.py — D to R pipeline Phase 2a: Preview Delivery entry point."""
from services.delivery import deliver_preview as main
from integrations.delivery_status import mark_delivery_run

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    try:
        mark_delivery_run(status="running", stage="starting")
        main()
    except BaseException as exc:
        mark_delivery_run(status="failed", stage="failed", error=str(exc))
        raise
    else:
        mark_delivery_run(status="succeeded", stage="finished")

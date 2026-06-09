"""deliver.py — D to R pipeline Phase 2a: Preview Delivery entry point."""
from services.delivery import deliver_preview as main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    main()

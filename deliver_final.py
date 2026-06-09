"""deliver_final.py — D to R pipeline Phase 2b: Final Delivery entry point."""
from services.delivery import deliver_final as main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    main()

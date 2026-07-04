"""deliver.py — D to R pipeline Phase 2a: Preview Delivery entry point."""

import os
import sys


def _install_storage_backend_alias() -> None:
    backend = os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive"
    if backend == "drive":
        return
    import integrations.storage as storage
    sys.modules["integrations.drive"] = storage


_install_storage_backend_alias()

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

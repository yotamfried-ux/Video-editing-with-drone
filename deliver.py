"""
deliver.py — D to R pipeline Phase 2: Deliver.
Scans APPROVED folder → sends summary email to owner → moves reels to PROCESSED.

Usage:
  1. Review drafts in Drive REVIEW folder.
  2. Move approved reels from REVIEW → APPROVED folder.
  3. Run:  python deliver.py
"""

import logging
import os
import sys

# ── Logging ────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/pipeline.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ── Pipeline imports ────────────────────────────────────────────────────────
import config
from pipeline.drive    import get_approved_drafts, mark_draft_delivered
from pipeline.notifier import send_summary_email


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n🚀 D to R Pipeline — Phase 2: Deliver")

    approved = get_approved_drafts()
    if not approved:
        print("✅ No approved drafts — nothing to deliver")
        return

    print(f"\n📋 {len(approved)} approved reel(s) ready to deliver")

    links     = [d["webViewLink"] for d in approved]
    sport_tag = "mixed"
    name_tag  = approved[0]["name"] if len(approved) == 1 else f"{len(approved)} approved reels"

    try:
        send_summary_email(
            recipients  = [config.OWNER_EMAIL],
            clips_links = links,
            sport_type  = sport_tag,
            video_name  = name_tag,
        )
        print(f"✉️  Delivery email sent to {config.OWNER_EMAIL}")
    except Exception:
        logger.error("Failed to send delivery email")
        print("❌ Failed to send delivery email")
        return

    delivered = 0
    for draft in approved:
        mark_draft_delivered(draft["id"])
        delivered += 1
        print(f"✅ Archived: {draft['name']}")

    logger.info("Phase 2 complete. Delivered: %d", delivered)
    print(f"\n✅ {delivered} reel(s) delivered and archived to PROCESSED folder")


if __name__ == "__main__":
    main()

"""
deliver.py — D to R pipeline Phase 2: Deliver.
Scans APPROVED folder → sends personal email to each matched athlete → batch email to owner
→ moves reels to PROCESSED.

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
from pipeline.clients  import find_client


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n🚀 D to R Pipeline — Phase 2: Deliver")

    approved = get_approved_drafts()
    if not approved:
        print("✅ No approved drafts — nothing to deliver")
        return

    print(f"\n📋 {len(approved)} approved reel(s) ready to deliver")

    # ── Per-athlete personal email ─────────────────────────────────────────
    sent_to_clients = 0
    for draft in approved:
        client = find_client(draft["name"])
        if not client:
            continue
        email = client.get("email", "")
        if not email or email == config.OWNER_EMAIL:
            continue
        try:
            send_summary_email(
                recipients  = [email],
                clips_links = [draft["webViewLink"]],
                sport_type  = "mixed",
                video_name  = draft["name"],
            )
            print(f"✉️  Personal reel sent to {email} ({client.get('name', '')})")
            sent_to_clients += 1
        except Exception:
            logger.error("Failed to send personal email to %s for %s", email, draft["name"])

    # ── Batch summary email to owner ───────────────────────────────────────
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
        print(f"✉️  Batch summary sent to owner ({config.OWNER_EMAIL})")
    except Exception:
        logger.error("Failed to send owner summary email")
        print("❌ Failed to send owner summary email — continuing to archive")

    # ── Archive delivered reels ────────────────────────────────────────────
    delivered = 0
    for draft in approved:
        mark_draft_delivered(draft["id"])
        delivered += 1
        print(f"✅ Archived: {draft['name']}")

    logger.info(
        "Phase 2 complete. Delivered: %d, Client emails: %d",
        delivered, sent_to_clients,
    )
    print(f"\n✅ {delivered} reel(s) delivered and archived to PROCESSED folder")
    if sent_to_clients:
        print(f"   {sent_to_clients} personal athlete email(s) sent")


if __name__ == "__main__":
    main()

"""
deliver_final.py — D to R pipeline Phase 2b: Final Delivery.
Scans PENDING_PAYMENT folder → sends full-quality Drive link to athlete after payment.

Usage:
  1. Athlete pays.
  2. Run:  python deliver_final.py
"""

import json
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
from pipeline.drive    import get_pending_payment_drafts, mark_draft_delivered
from pipeline.notifier import send_summary_email
from pipeline.clients  import find_client


# ── Delivered-IDs local state ──────────────────────────────────────────────

_DELIVERED_FILE = "delivered.json"


def _load_delivered() -> set[str]:
    try:
        with open(_DELIVERED_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_delivered(ids: set[str]) -> None:
    tmp = _DELIVERED_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(list(ids), f, indent=2)
    os.replace(tmp, _DELIVERED_FILE)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n💳 D to R Pipeline — Phase 2b: Final Delivery")

    pending = get_pending_payment_drafts()
    if not pending:
        print("✅ No reels pending payment — nothing to deliver")
        return

    already_delivered = _load_delivered()
    to_deliver = [d for d in pending if d["id"] not in already_delivered]
    skipped    = len(pending) - len(to_deliver)
    if skipped:
        print(f"⏭️  Skipping {skipped} already-delivered reel(s)")

    no_link    = [d for d in to_deliver if not d.get("webViewLink")]
    to_deliver = [d for d in to_deliver if d.get("webViewLink")]
    for d in no_link:
        logger.warning("⚠️ No webViewLink for '%s' — skipping email", d["name"])

    print(f"\n📋 {len(to_deliver)} reel(s) to deliver")

    # ── Per-athlete personal email ─────────────────────────────────────────
    sent_to_clients = 0
    for draft in to_deliver:
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
            print(f"✉️  Full reel sent to {email} ({client.get('name', '')})")
            sent_to_clients += 1
        except Exception:
            logger.error("Failed to send final email to %s for %s", email, draft["name"])

    # ── Batch summary email to owner ───────────────────────────────────────
    if to_deliver:
        try:
            send_summary_email(
                recipients  = [config.OWNER_EMAIL],
                clips_links = [d["webViewLink"] for d in to_deliver],
                sport_type  = "mixed",
                video_name  = (to_deliver[0]["name"] if len(to_deliver) == 1
                               else f"{len(to_deliver)} final reels delivered"),
            )
            print(f"✉️  Final delivery summary sent to owner ({config.OWNER_EMAIL})")
        except Exception:
            logger.error("Failed to send owner final delivery summary")
            print("❌ Failed to send owner summary — still archiving")

        _save_delivered(_load_delivered() | {d["id"] for d in to_deliver})

    # ── Archive all pending reels (including already-delivered) ─────────────
    for draft in pending:
        mark_draft_delivered(draft["id"])
        print(f"✅ Archived: {draft['name']}")

    logger.info("Phase 2b complete. Delivered: %d, Client emails: %d",
                len(to_deliver), sent_to_clients)
    print(f"\n✅ {len(to_deliver)} full-quality reel(s) delivered and archived")
    if sent_to_clients:
        print(f"   {sent_to_clients} personal delivery email(s) sent")


if __name__ == "__main__":
    main()

"""
deliver.py — D to R pipeline Phase 2a: Preview Delivery.
Scans APPROVED folder → downloads each reel → generates 480p watermarked preview
→ uploads preview → emails preview link to athlete → moves original to PENDING_PAYMENT.

After payment is confirmed:
  Run:  python deliver_final.py
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
from pipeline.drive    import (get_approved_drafts, download_video,
                                upload_preview, move_to_pending_payment)
from pipeline.editor   import create_preview
from pipeline.notifier import send_summary_email
from pipeline.clients  import find_client


# ── Previewed-IDs local state ──────────────────────────────────────────────

_PREVIEWED_FILE = "previewed.json"


def _load_previewed() -> set[str]:
    try:
        with open(_PREVIEWED_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_previewed(ids: set[str]) -> None:
    tmp = _PREVIEWED_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(list(ids), f, indent=2)
    os.replace(tmp, _PREVIEWED_FILE)


def _mark_previewed(ids_to_add: set[str]) -> None:
    _save_previewed(_load_previewed() | ids_to_add)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n🔍 D to R Pipeline — Phase 2a: Preview Delivery")

    approved = get_approved_drafts()
    if not approved:
        print("✅ No approved drafts — nothing to preview")
        return

    already_previewed = _load_previewed()
    to_preview = [d for d in approved if d["id"] not in already_previewed]
    skipped    = len(approved) - len(to_preview)
    if skipped:
        print(f"⏭️  Skipping {skipped} already-previewed reel(s)")

    no_link    = [d for d in to_preview if not d.get("webViewLink")]
    to_preview = [d for d in to_preview if d.get("webViewLink")]
    for d in no_link:
        logger.warning("⚠️ No webViewLink for '%s' — skipping", d["name"])
        print(f"⚠️ No link for '{d['name']}' — skipped (check Drive permissions)")

    print(f"\n📋 {len(to_preview)} reel(s) to preview")

    # ── Per-reel: download → preview → upload → move ───────────────────────
    preview_results: list[tuple[dict, str, dict | None]] = []  # (draft, link, client)

    for draft in to_preview:
        client = find_client(draft["name"])
        athlete_name = client.get("name", "") if client else ""

        local_path   = None
        preview_path = None

        try:
            local_path   = download_video(draft["id"], draft["name"])
            preview_path = create_preview(local_path, athlete_label=athlete_name)
        except Exception as exc:
            logger.error("Preview prep failed for '%s': %s", draft["name"], exc)
            continue
        finally:
            if local_path:
                try: os.remove(local_path)
                except OSError: pass

        try:
            preview_name = draft["name"].replace(".mp4", "_preview.mp4")
            preview_link = upload_preview(preview_path, preview_name)
        except Exception as exc:
            logger.error("Preview upload failed for '%s': %s", draft["name"], exc)
            continue
        finally:
            if preview_path:
                try: os.remove(preview_path)
                except OSError: pass

        move_to_pending_payment(draft["id"])
        preview_results.append((draft, preview_link, client))

    if not preview_results:
        print("\n⚠️ No previews produced")
        return

    # ── Per-athlete personal preview email ─────────────────────────────────
    sent_to_clients = 0
    for draft, preview_link, client in preview_results:
        if not client:
            continue
        email = client.get("email", "")
        if not email or email == config.OWNER_EMAIL:
            continue
        try:
            send_summary_email(
                recipients  = [email],
                clips_links = [preview_link],
                sport_type  = "mixed",
                video_name  = draft["name"],
            )
            print(f"✉️  Preview sent to {email} ({client.get('name', '')})")
            sent_to_clients += 1
        except Exception:
            logger.error("Failed to send preview email to %s for %s", email, draft["name"])

    # ── Batch summary email to owner ───────────────────────────────────────
    try:
        send_summary_email(
            recipients  = [config.OWNER_EMAIL],
            clips_links = [link for _, link, _ in preview_results],
            sport_type  = "mixed",
            video_name  = (preview_results[0][0]["name"] if len(preview_results) == 1
                           else f"{len(preview_results)} previews ready"),
        )
        print(f"✉️  Preview summary sent to owner ({config.OWNER_EMAIL})")
    except Exception:
        logger.error("Failed to send owner preview summary")
        print("❌ Failed to send owner summary — previews are still in Drive")

    _mark_previewed({d["id"] for d, _, _ in preview_results})

    logger.info("Phase 2a complete. Previews sent: %d, Client emails: %d",
                len(preview_results), sent_to_clients)
    print(f"\n✅ {len(preview_results)} preview(s) ready in PENDING_PAYMENT folder")
    if sent_to_clients:
        print(f"   {sent_to_clients} personal preview email(s) sent")
    print("   After payment: run  python deliver_final.py")


if __name__ == "__main__":
    main()

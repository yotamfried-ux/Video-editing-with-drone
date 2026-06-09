"""
services/delivery.py — Delivery service (Phase 2a + 2b).

deliver_preview():  Approved reels → 480p watermarked preview → email athlete → move to pending_payment.
deliver_final():    Pending-payment reels → full-quality Drive link → email athlete → archive.
"""

import json
import logging
import os

import config
from integrations.drive    import (get_approved_drafts, download_video,
                                    upload_preview, move_to_pending_payment,
                                    get_pending_payment_drafts, mark_draft_delivered)
from pipeline.stages.editor   import create_preview
from integrations.notifier import send_summary_email
from services.client_manager  import find_client
from pipeline.stages.feedback import record_approval as _record_approval

logger = logging.getLogger(__name__)

# ── State files ────────────────────────────────────────────────────────────

_PREVIEWED_FILE = "previewed.json"
_DELIVERED_FILE = "delivered.json"


def _load_reel_metadata(draft_name: str) -> dict | None:
    try:
        with open(config.REEL_METADATA_FILE) as f:
            return json.load(f).get(draft_name)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return None


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


# ── Phase 2a ───────────────────────────────────────────────────────────────

def deliver_preview() -> None:
    """Scan APPROVED folder → generate 480p preview → email → move to PENDING_PAYMENT."""
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

    preview_results: list[tuple[dict, str, dict | None]] = []

    for draft in to_preview:
        client       = find_client(draft["name"])
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
        _mark_previewed({draft["id"]})
        preview_results.append((draft, preview_link, client))

        reel_meta = _load_reel_metadata(draft["name"])
        if reel_meta:
            try:
                _record_approval(
                    sport          = reel_meta.get("sport", "unknown"),
                    events         = reel_meta.get("events", []),
                    source_quality = reel_meta.get("source_quality"),
                )
            except Exception as _fe:
                logger.warning("Feedback record failed for %s: %s", draft["name"], _fe)

    if not preview_results:
        print("\n⚠️ No previews produced")
        return

    athlete_groups: dict[str, dict] = {}
    for draft, preview_link, client in preview_results:
        base = draft["name"].replace("_music", "").replace("__", "_")
        if base not in athlete_groups:
            athlete_groups[base] = {"links": [], "client": client, "draft": draft}
        if "_music" in draft["name"]:
            athlete_groups[base]["links"].append(preview_link)
        else:
            athlete_groups[base]["links"].insert(0, preview_link)

    sent_to_clients = 0
    for base_name, group in athlete_groups.items():
        client = group["client"]
        if not client:
            continue
        email = client.get("email", "")
        if not email or email == config.OWNER_EMAIL:
            continue
        try:
            send_summary_email(
                recipients  = [email],
                clips_links = group["links"],
                sport_type  = "mixed",
                video_name  = group["draft"]["name"],
            )
            print(f"✉️  Preview sent to {email} ({client.get('name', '')})")
            sent_to_clients += 1
        except Exception:
            logger.error("Failed to send preview email to %s for %s", email, group["draft"]["name"])

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

    logger.info("Phase 2a complete. Previews sent: %d, Client emails: %d",
                len(preview_results), sent_to_clients)
    print(f"\n✅ {len(preview_results)} preview(s) ready in PENDING_PAYMENT folder")
    if sent_to_clients:
        print(f"   {sent_to_clients} personal preview email(s) sent")
    print("   After payment: run  python deliver_final.py")


# ── Phase 2b ───────────────────────────────────────────────────────────────

def deliver_final() -> None:
    """Scan PENDING_PAYMENT folder → send full-quality link → archive."""
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

    _last_delivered_path: dict[str, str] = {}

    sent_to_clients = 0
    for draft in to_deliver:
        try:
            local_path = download_video(draft["id"], draft["name"])
            _last_delivered_path[draft["id"]] = local_path
        except Exception as exc:
            logger.warning("Could not download '%s' for SportReel publish: %s", draft["name"], exc)

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

    delivered_ids = {d["id"] for d in to_deliver}
    for draft in pending:
        if draft["id"] not in delivered_ids and draft["id"] not in already_delivered:
            logger.warning(
                "Archiving '%s' with no client match — no email was sent", draft["name"]
            )
            print(f"⚠️  No client match for '{draft['name']}' — archived without email delivery")
        mark_draft_delivered(draft["id"])
        try:
            from integrations.supabase_uploader import publish_reel as _publish_reel
            reel_meta = _load_reel_metadata(draft["name"]) or {}
            shareable_url = _publish_reel(
                local_path=_last_delivered_path.get(draft["id"], ""),
                athlete_desc=reel_meta.get("description", ""),
                sport=reel_meta.get("sport", "unknown"),
                drive_file_id=draft["id"],
            )
            print(f"🌐 Published to SportReel: {shareable_url}")
        except Exception as _exc:
            logger.warning("SportReel publish skipped: %s", _exc)
        print(f"✅ Archived: {draft['name']}")

    for _local in _last_delivered_path.values():
        try:
            os.remove(_local)
        except OSError:
            pass

    logger.info("Phase 2b complete. Delivered: %d, Client emails: %d",
                len(to_deliver), sent_to_clients)
    print(f"\n✅ {len(to_deliver)} full-quality reel(s) delivered and archived")
    if sent_to_clients:
        print(f"   {sent_to_clients} personal delivery email(s) sent")

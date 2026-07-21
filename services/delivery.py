"""services/delivery.py — delivery service for approved SportReel outputs.

Delivery intentionally does not identify app users from faces. Approved reels are
published to Discover and delivered through explicit client/contact and purchase
flows only.
"""

import json
import logging
import os

import config
from integrations.delivery_status import mark_delivery_run
from integrations.drive import (
    download_video,
    get_approved_drafts,
    get_pending_payment_drafts,
    mark_draft_delivered,
    move_to_pending_payment,
    upload_preview,
)
from integrations.notifier import send_summary_email
from pipeline.stages.editor import create_preview
from pipeline.stages.feedback import record_approval as _record_approval
from services.client_manager import find_client

logger = logging.getLogger(__name__)

_PREVIEWED_FILE = "previewed.json"
_DELIVERED_FILE = "delivered.json"


def _load_reel_metadata(draft_name: str) -> dict | None:
    try:
        with open(config.REEL_METADATA_FILE) as handle:
            return json.load(handle).get(draft_name)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return None


def _load_ids(path: str) -> set[str]:
    try:
        with open(path) as handle:
            return set(json.load(handle))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_ids(path: str, values: set[str]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(list(values), handle, indent=2)
    os.replace(tmp, path)


def _load_previewed() -> set[str]:
    return _load_ids(_PREVIEWED_FILE)


def _mark_previewed(ids_to_add: set[str]) -> None:
    _save_ids(_PREVIEWED_FILE, _load_previewed() | ids_to_add)


def _load_delivered() -> set[str]:
    return _load_ids(_DELIVERED_FILE)


def _save_delivered(ids: set[str]) -> None:
    _save_ids(_DELIVERED_FILE, ids)


def _remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def deliver_preview() -> None:
    """Approved reels -> preview -> Discover -> pending payment.

    No still frame, embedding, biometric comparison, or automatic user ownership
    assignment is performed.
    """
    print("\n🔍 D to R Pipeline — Phase 2a: Preview Delivery")
    mark_delivery_run(status="running", stage="scanning_approved")

    approved = get_approved_drafts()
    target_file_id = os.getenv("DELIVERY_APPROVED_FILE_ID", "").strip()
    if target_file_id:
        approved = [draft for draft in approved if draft.get("id") == target_file_id]
    if not approved:
        print("✅ No approved drafts — nothing to preview")
        mark_delivery_run(status="succeeded", stage="no_approved_drafts")
        return

    already_previewed = _load_previewed()
    to_preview = [draft for draft in approved if draft["id"] not in already_previewed]
    skipped = len(approved) - len(to_preview)
    if skipped:
        print(f"⏭️  Skipping {skipped} already-previewed reel(s)")

    missing_link = [draft for draft in to_preview if not draft.get("webViewLink")]
    to_preview = [draft for draft in to_preview if draft.get("webViewLink")]
    for draft in missing_link:
        logger.warning("No webViewLink for '%s' — skipping", draft["name"])

    print(f"\n📋 {len(to_preview)} reel(s) to preview")
    mark_delivery_run(
        status="running",
        stage="previewing",
        meta={"approved_count": len(to_preview)},
    )

    preview_results: list[tuple[dict, str, dict | None]] = []
    for draft in to_preview:
        client = find_client(draft["name"])
        athlete_name = client.get("name", "") if client else ""
        local_path = None
        preview_path = None
        try:
            mark_delivery_run(
                status="running",
                stage="creating_preview",
                source_video=draft["name"],
            )
            local_path = download_video(draft["id"], draft["name"])
            preview_path = create_preview(local_path, athlete_label=athlete_name)
        except Exception as exc:
            logger.error("Preview prep failed for '%s': %s", draft["name"], exc)
            mark_delivery_run(
                status="running",
                stage="preview_failed",
                error=str(exc),
                source_video=draft["name"],
            )
            continue
        finally:
            _remove(local_path)

        try:
            preview_name = draft["name"].replace(".mp4", "_preview.mp4")
            preview_link = upload_preview(preview_path, preview_name)

            try:
                mark_delivery_run(
                    status="running",
                    stage="publishing_discover",
                    source_video=draft["name"],
                )
                from integrations.supabase_uploader import publish_reel_approved

                reel_id = publish_reel_approved(
                    preview_path=preview_path,
                    draft_name=draft["name"],
                    drive_file_id=draft["id"],
                    reel_meta=_load_reel_metadata(draft["name"]) or {},
                )
                mark_delivery_run(
                    status="discover_published",
                    stage="discover_published",
                    discover_reel_id=reel_id,
                    source_video=draft["name"],
                )
                print(f"📱 '{draft['name']}' published to Discover (id={reel_id})")
            except Exception as exc:
                logger.warning("Discover publish failed for '%s': %s", draft["name"], exc)
                mark_delivery_run(
                    status="running",
                    stage="discover_publish_failed",
                    error=str(exc),
                    source_video=draft["name"],
                )
        except Exception as exc:
            logger.error("Preview upload failed for '%s': %s", draft["name"], exc)
            mark_delivery_run(
                status="running",
                stage="preview_upload_failed",
                error=str(exc),
                source_video=draft["name"],
            )
            continue
        finally:
            _remove(preview_path)

        move_to_pending_payment(draft["id"])
        _mark_previewed({draft["id"]})
        preview_results.append((draft, preview_link, client))

        reel_meta = _load_reel_metadata(draft["name"])
        if reel_meta:
            try:
                _record_approval(
                    sport=reel_meta.get("sport", "unknown"),
                    events=reel_meta.get("events", []),
                    source_quality=reel_meta.get("source_quality"),
                )
            except Exception as exc:
                logger.warning("Feedback record failed for %s: %s", draft["name"], exc)

    if not preview_results:
        print("\n⚠️ No previews produced")
        return

    athlete_groups: dict[str, dict] = {}
    for draft, preview_link, client in preview_results:
        base = draft["name"].replace("_music", "").replace("__", "_")
        if base not in athlete_groups:
            athlete_groups[base] = {"links": [], "client": client, "draft": draft}
        athlete_groups[base]["links"].append(preview_link)

    sent_to_clients = 0
    for group in athlete_groups.values():
        client = group["client"]
        if not client:
            continue
        email = client.get("email", "")
        if not email or email == config.OWNER_EMAIL:
            continue
        try:
            mark_delivery_run(status="discover_published", stage="emailing_athlete")
            send_summary_email(
                recipients=[email],
                clips_links=group["links"],
                sport_type="mixed",
                video_name=group["draft"]["name"],
            )
            sent_to_clients += 1
        except Exception:
            logger.error("Failed to send preview email to %s", email)

    try:
        send_summary_email(
            recipients=[config.OWNER_EMAIL],
            clips_links=[link for _, link, _ in preview_results],
            sport_type="mixed",
            video_name=(
                preview_results[0][0]["name"]
                if len(preview_results) == 1
                else f"{len(preview_results)} previews ready"
            ),
        )
    except Exception:
        logger.error("Failed to send owner preview summary")

    logger.info(
        "Phase 2a complete. Previews: %d, client emails: %d",
        len(preview_results),
        sent_to_clients,
    )
    print(f"\n✅ {len(preview_results)} preview(s) ready in PENDING_PAYMENT folder")


def _publish_final_reel(draft: dict, local_path: str) -> None:
    """Publish one full-quality reel while its bounded local file is available."""
    if not local_path:
        logger.warning("SportReel publish skipped for '%s': local download unavailable", draft["name"])
        return
    try:
        from integrations.supabase_uploader import _supabase, publish_reel

        existing = (
            _supabase()
            .table("reels")
            .select("id")
            .eq("source_video", draft["name"])
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        reel_meta = _load_reel_metadata(draft["name"]) or {}
        publish_reel(
            local_path=local_path,
            athlete_desc=reel_meta.get("description", ""),
            sport=reel_meta.get("sport", "unknown"),
            drive_file_id=draft["id"],
        )
    except Exception as exc:
        logger.warning("SportReel publish skipped for '%s': %s", draft["name"], exc)


def deliver_final() -> None:
    """Pending-payment reels -> explicit delivery link -> archive.

    Full-quality 4K files are processed one at a time and removed in ``finally``
    so batch size cannot multiply temporary disk usage.
    """
    print("\n💳 D to R Pipeline — Phase 2b: Final Delivery")
    pending = get_pending_payment_drafts()
    if not pending:
        print("✅ No reels pending payment — nothing to deliver")
        return

    already_delivered = _load_delivered()
    to_deliver = [draft for draft in pending if draft["id"] not in already_delivered]
    skipped = len(pending) - len(to_deliver)
    if skipped:
        print(f"⏭️  Skipping {skipped} already-delivered reel(s)")

    missing_link = [draft for draft in to_deliver if not draft.get("webViewLink")]
    to_deliver = [draft for draft in to_deliver if draft.get("webViewLink")]
    for draft in missing_link:
        logger.warning("No webViewLink for '%s' — skipping email", draft["name"])

    print(f"\n📋 {len(to_deliver)} reel(s) to deliver")
    sent_to_clients = 0

    for draft in to_deliver:
        local_path = None
        try:
            local_path = download_video(draft["id"], draft["name"])
            _publish_final_reel(draft, local_path)

            client = find_client(draft["name"])
            if not client:
                continue
            email = client.get("email", "")
            if not email or email == config.OWNER_EMAIL:
                continue
            try:
                send_summary_email(
                    recipients=[email],
                    clips_links=[draft["webViewLink"]],
                    sport_type="mixed",
                    video_name=draft["name"],
                )
                sent_to_clients += 1
            except Exception:
                logger.error("Failed to send final email to %s for %s", email, draft["name"])
        except Exception as exc:
            logger.warning("Could not prepare final delivery for '%s': %s", draft["name"], exc)
        finally:
            _remove(local_path)

    if to_deliver:
        try:
            send_summary_email(
                recipients=[config.OWNER_EMAIL],
                clips_links=[draft["webViewLink"] for draft in to_deliver],
                sport_type="mixed",
                video_name=(
                    to_deliver[0]["name"]
                    if len(to_deliver) == 1
                    else f"{len(to_deliver)} final reels delivered"
                ),
            )
        except Exception:
            logger.error("Failed to send owner final delivery summary")
        _save_delivered(_load_delivered() | {draft["id"] for draft in to_deliver})

    delivered_ids = {draft["id"] for draft in to_deliver}
    for draft in pending:
        if draft["id"] not in delivered_ids and draft["id"] not in already_delivered:
            logger.warning("Archiving '%s' without a configured client email", draft["name"])
        mark_draft_delivered(draft["id"])

    logger.info(
        "Phase 2b complete. Delivered: %d, client emails: %d",
        len(to_deliver),
        sent_to_clients,
    )
    print(f"\n✅ {len(to_deliver)} full-quality reel(s) delivered and archived")

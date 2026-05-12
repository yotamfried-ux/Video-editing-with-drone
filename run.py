"""
run.py — D to R pipeline entry point.
מריץ את כל שלבי הפייפליין: סריקה → הורדה → ניתוח → עריכה → העלאה → שליחה.
"""

import json
import logging
import os
import sys
from pathlib import Path

# ── Logging setup (must happen before importing pipeline modules) ───────────
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
import config  # noqa: E402
from pipeline.drive import download_video, get_new_videos, mark_as_processed, upload_clip
from pipeline.analyzer import analyze_video
from pipeline.editor import cut_and_watermark
from pipeline.notifier import send_summary_email


# ── Client lookup ──────────────────────────────────────────────────────────

def _load_clients() -> list[dict]:
    """
    Load clients.json if it exists.
    Format: [{"name": "...", "email": "...", "video_pattern": "..."}]
    """
    if not Path(config.CLIENTS_FILE).exists():
        return []
    try:
        with open(config.CLIENTS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("⚠️ Could not read %s: %s", config.CLIENTS_FILE, e)
        return []


def _find_client_email(video_name: str) -> str | None:
    """
    Match the video filename against clients.json patterns (case-insensitive substring).
    Returns the client email, or None if no match found.
    If no match → email is sent to OWNER_EMAIL only.
    """
    clients = _load_clients()
    name_lower = video_name.lower()
    for client in clients:
        pattern = str(client.get("video_pattern", "")).lower()
        if pattern and pattern in name_lower:
            email = client.get("email", "").strip()
            if email:
                print(f"✅ Matched client: {client.get('name', email)} → {email}")
                return email
    return None


# ── Single-video processor ─────────────────────────────────────────────────

def process_video(file_meta: dict) -> dict:
    """
    Run the full pipeline for a single video.
    Returns {"links": [...], "sport": str, "filename": str}.
    """
    file_id:  str = file_meta["id"]
    filename: str = file_meta["name"]
    print(f"\n{'='*60}")
    print(f"🎬 Processing: {filename}")
    print(f"{'='*60}")

    # 1. Download
    try:
        local_path = download_video(file_id, filename)
    except Exception:
        logger.error("Skipping %s — download failed", filename)
        return {"links": [], "sport": "unknown", "filename": filename}

    # 2. Analyze with Claude
    analysis = analyze_video(local_path)
    sport  = analysis.get("sport", "unknown")
    events = analysis.get("events", [])

    if not events:
        print(f"⚠️ No highlights detected in '{filename}', skipping.")
        logger.warning("No highlights for %s", filename)
        mark_as_processed(file_id)
        try:
            os.remove(local_path)
        except OSError:
            pass
        return {"links": [], "sport": sport, "filename": filename}

    print(f"🎬 Sport: {sport} | Events to cut: {len(events)}")

    # 3. Cut + watermark each event, then upload
    clip_links: list[str] = []
    for i, event in enumerate(events, start=1):
        clip_path = cut_and_watermark(local_path, event, index=i)
        if clip_path is None:
            print(f"⚠️ Clip {i} failed — skipping upload")
            continue

        clip_name = os.path.basename(clip_path)
        try:
            link = upload_clip(clip_path, clip_name)
            clip_links.append(link)
        except Exception:
            logger.error("Upload failed for %s", clip_name)
        finally:
            try:
                os.remove(clip_path)
            except OSError:
                pass

    # 4. Mark original as processed and clean up
    mark_as_processed(file_id)
    try:
        os.remove(local_path)
    except OSError:
        pass

    print(f"✅ Done with '{filename}' — {len(clip_links)} clip(s) uploaded")
    return {"links": clip_links, "sport": sport, "filename": filename}


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n🎬 D to R Pipeline — Starting")
    print(f"📁 Tmp dir: {config.TMP_DIR}")

    new_videos = get_new_videos()

    if not new_videos:
        print("✅ No new videos to process. Exiting.")
        return

    total_clips = 0

    for video_meta in new_videos:
        result   = process_video(video_meta)
        links    = result["links"]
        sport    = result["sport"]
        filename = result["filename"]

        if not links:
            continue

        total_clips += len(links)

        # Build recipients list: always start with the owner.
        # Add the filmed client only if their email is in clients.json.
        # If no client match → email goes to OWNER_EMAIL only.
        recipients: list[str] = [config.OWNER_EMAIL]
        client_email = _find_client_email(filename)
        if client_email and client_email != config.OWNER_EMAIL:
            recipients.append(client_email)
        else:
            print(f"📧 No client match for '{filename}' — sending to owner only")

        send_summary_email(
            recipients=recipients,
            clips_links=links,
            sport_type=sport,
            video_name=filename,
        )

    if total_clips:
        print(f"\n🎬 Pipeline complete — {total_clips} clip(s) delivered across {len(new_videos)} video(s)")
    else:
        print("\n⚠️ Pipeline complete — no clips were produced")

    logger.info("Pipeline run finished. Videos: %d, Clips: %d", len(new_videos), total_clips)


if __name__ == "__main__":
    main()

"""
run.py — D to R pipeline entry point.
מריץ את כל שלבי הפייפליין: סריקה → הורדה → ניתוח → עריכה → העלאה → שליחה.
"""

import logging
import os
import sys

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
import config  # noqa: E402  (import after logging)
from pipeline.drive import download_video, get_new_videos, mark_as_processed, upload_clip
from pipeline.analyzer import analyze_video
from pipeline.editor import cut_and_watermark
from pipeline.notifier import send_summary_email


def process_video(file_meta: dict) -> list[str]:
    """
    Full pipeline for a single video file.
    Returns list of Drive clip links (empty list on failure).
    """
    file_id: str = file_meta["id"]
    filename: str = file_meta["name"]
    print(f"\n{'='*60}")
    print(f"🎬 Processing: {filename}")
    print(f"{'='*60}")

    # 1. Download
    try:
        local_path = download_video(file_id, filename)
    except Exception:
        logger.error("Skipping %s — download failed", filename)
        return []

    # 2. Analyze with Gemini
    analysis = analyze_video(local_path)
    sport = analysis.get("sport", "unknown")
    events = analysis.get("events", [])

    if not events:
        print(f"⚠️ No highlights detected in '{filename}', skipping.")
        logger.warning("No highlights for %s", filename)
        mark_as_processed(file_id)
        return []

    print(f"🎬 Sport: {sport} | Events to cut: {len(events)}")

    # 3. Cut + watermark each event
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
            continue

        # Clean up local clip to save disk space
        try:
            os.remove(clip_path)
        except OSError:
            pass

    # 4. Mark original as processed and clean up local download
    mark_as_processed(file_id)
    try:
        os.remove(local_path)
    except OSError:
        pass

    print(f"✅ Done with '{filename}' — {len(clip_links)} clip(s) uploaded")
    return clip_links


def main() -> None:
    print("\n🎬 D to R Pipeline — Starting")
    print(f"📁 Tmp dir: {config.TMP_DIR}")

    # Scan for new videos
    new_videos = get_new_videos()

    if not new_videos:
        print("✅ No new videos to process. Exiting.")
        return

    all_links: list[str] = []
    last_sport = "unknown"
    last_name = "drone_footage"

    for video_meta in new_videos:
        links = process_video(video_meta)
        all_links.extend(links)
        # Track last processed sport/name for the summary email
        if links:
            last_name = video_meta["name"]
            # Re-read sport from analysis result if we had it — use placeholder
            # (sport is determined inside process_video; for multi-video runs the
            # email summarises all clips together under the last detected sport)
            last_sport = "mixed" if len(new_videos) > 1 else last_sport

    # Send a single summary email for the entire run
    if all_links:
        send_summary_email(
            client_email=config.NOTIFY_EMAIL,
            clips_links=all_links,
            sport_type=last_sport,
            video_name=last_name if len(new_videos) == 1 else f"{len(new_videos)} videos",
        )
        print(f"\n🎬 Pipeline complete — {len(all_links)} clip(s) delivered")
    else:
        print("\n⚠️ Pipeline complete — no clips were produced")

    logger.info("Pipeline run finished. Videos processed: %d, Clips delivered: %d",
                len(new_videos), len(all_links))


if __name__ == "__main__":
    main()

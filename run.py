"""
run.py — D to R pipeline entry point.
סריקה → הורדה → ניתוח → ריל אחד → העלאה → מייל.
"""

import json
import logging
import os
import sys
from pathlib import Path

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
from pipeline.drive    import download_video, get_new_videos, mark_as_processed, upload_clip
from pipeline.analyzer import analyze_video
from pipeline.editor   import create_reel
from pipeline.notifier import send_summary_email


# ── Client lookup ──────────────────────────────────────────────────────────

def _load_clients() -> list[dict]:
    if not Path(config.CLIENTS_FILE).exists():
        return []
    try:
        with open(config.CLIENTS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("⚠️ Could not read %s: %s", config.CLIENTS_FILE, e)
        return []


def _find_client(video_name: str) -> dict | None:
    """
    מחפש לקוח ב-clients.json לפי video_pattern (substring, case-insensitive).
    מחזיר את כל ה-dict של הלקוח (שם + מייל), או None אם לא נמצא.
    אם לא נמצא התאמה — המייל ישלח לבעלים בלבד.
    """
    name_lower = video_name.lower()
    for client in _load_clients():
        pattern = str(client.get("video_pattern", "")).lower()
        if pattern and pattern in name_lower:
            email = client.get("email", "").strip()
            if email:
                print(f"✅ Client match: {client.get('name', email)} → {email}")
                return client
    return None


# ── Single-video processor ─────────────────────────────────────────────────

def process_video(file_meta: dict) -> dict:
    """
    מעבד סרטון אחד מתחילה לסוף.
    מחזיר {"reel_path": str|None, "reel_link": str|None, "sport": str, "filename": str}
    """
    file_id  = file_meta["id"]
    filename = file_meta["name"]

    print(f"\n{'='*60}")
    print(f"🎬 Processing: {filename}")
    print(f"{'='*60}")

    # 1. הורדה
    try:
        local_path = download_video(file_id, filename)
    except Exception:
        logger.error("Skipping %s — download failed", filename)
        return {"reel_path": None, "reel_link": None, "sport": "unknown", "filename": filename}

    # 2. ניתוח עם Claude
    analysis = analyze_video(local_path)
    sport    = analysis.get("sport", "unknown")
    events   = analysis.get("events", [])

    if not events:
        print(f"⚠️ No highlights in '{filename}' — skipping")
        mark_as_processed(file_id)
        try: os.remove(local_path)
        except OSError: pass
        return {"reel_path": None, "reel_link": None, "sport": sport, "filename": filename}

    print(f"🎬 Sport: {sport} | Highlights: {len(events)}")

    # 3. עריכה: קליפים בודדים → ריל אחד
    reel_path = create_reel(local_path, events, sport)

    # 4. העלאה
    reel_link = None
    if reel_path:
        reel_name = Path(reel_path).name
        try:
            reel_link = upload_clip(reel_path, reel_name)
        except Exception:
            logger.error("Upload failed for reel %s", reel_name)
        finally:
            try: os.remove(reel_path)
            except OSError: pass

    # 5. סימון כמעובד + ניקוי
    mark_as_processed(file_id)
    try: os.remove(local_path)
    except OSError: pass

    status = "✅" if reel_link else "⚠️ no reel uploaded"
    print(f"{status} Done: '{filename}'")
    return {"reel_path": reel_path, "reel_link": reel_link, "sport": sport, "filename": filename}


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n🎬 D to R Pipeline — Starting")
    print(f"📁 Tmp dir: {config.TMP_DIR}")

    new_videos = get_new_videos()
    if not new_videos:
        print("✅ No new videos — exiting")
        return

    total_reels = 0

    for video_meta in new_videos:
        result    = process_video(video_meta)
        reel_link = result["reel_link"]
        sport     = result["sport"]
        filename  = result["filename"]

        if not reel_link:
            continue

        total_reels += 1

        # נמענים: תמיד הבעלים, + הלקוח אם נמצא ב-clients.json
        client     = _find_client(filename)
        recipients = [config.OWNER_EMAIL]
        if client and client.get("email") and client["email"] != config.OWNER_EMAIL:
            recipients.append(client["email"])
        else:
            print("📧 No client match — sending to owner only")

        send_summary_email(
            recipients  = recipients,
            clips_links = [reel_link],   # ריל אחד
            sport_type  = sport,
            video_name  = filename,
        )

    if total_reels:
        print(f"\n🎬 Pipeline complete — {total_reels} reel(s) delivered")
    else:
        print("\n⚠️ Pipeline complete — no reels were produced")

    logger.info("Run finished. Videos: %d, Reels: %d", len(new_videos), total_reels)


if __name__ == "__main__":
    main()

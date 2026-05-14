"""
run.py — D to R pipeline Phase 1: Ingest & Draft.
Scans Drive RAW folder → identifies persons → creates per-person reels → uploads to REVIEW.

After reviewing drafts in Drive:
  1. Move approved reels from REVIEW → APPROVED folder.
  2. Run:  python deliver.py
"""

import logging
import os
import sys
from datetime import date
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
from pipeline.drive    import download_video, get_new_videos, mark_as_processed, upload_draft
from pipeline.analyzer import analyze_session
from pipeline.editor   import create_reel, compile_multi_source_reel
from pipeline.identity import cluster_clips


# ── Helpers ────────────────────────────────────────────────────────────────

def _classify_input(videos: list[dict]) -> str:
    """
    Heuristic: single large file (>100 MB) → full game/session → long_video mode.
    Multiple files or a single small file → short clips → clips_session mode.
    """
    if len(videos) == 1:
        try:
            size = int(videos[0].get("size", "0"))
        except (ValueError, TypeError):
            size = 0
        if size > 100_000_000:
            return "long_video"
    return "clips_session"


def _safe_draft_name(description: str) -> str:
    """Create a filesystem-safe draft filename from a person description."""
    safe  = "".join(c if c.isalnum() or c in " _-" else "_" for c in description)
    safe  = safe.strip()[:50].strip()
    today = date.today().strftime("%Y%m%d")
    return f"DRAFT_{safe}_{today}.mp4"


# ── Phase 1a: long video ───────────────────────────────────────────────────

def _process_long_video(video_meta: dict) -> int:
    """Download a single long video → analyze persons → create and upload per-person drafts."""
    file_id  = video_meta["id"]
    filename = video_meta["name"]

    print(f"\n{'='*60}")
    print(f"🎬 Long video: {filename}")
    print(f"{'='*60}")

    try:
        local_path = download_video(file_id, filename)
    except Exception:
        logger.error("Skipping %s — download failed", filename)
        return 0

    session  = analyze_session(local_path)
    activity = session.get("activity", "sport")
    persons  = session.get("persons", [])

    if not persons:
        print(f"⚠️ No persons detected in '{filename}' — skipping")
        mark_as_processed(file_id)
        try:
            os.remove(local_path)
        except OSError:
            pass
        return 0

    print(f"👥 Detected {len(persons)} person(s): "
          f"{', '.join(p['description'][:30] for p in persons)}")

    drafts = 0
    for person in persons:
        if not person.get("events"):
            continue
        reel = create_reel(local_path, person["events"], sport=activity)
        if not reel:
            continue
        name = _safe_draft_name(person["description"])
        try:
            upload_draft(reel, name)
            drafts += 1
        except Exception:
            logger.error("Draft upload failed for %s", name)
        finally:
            try:
                os.remove(reel)
            except OSError:
                pass

    mark_as_processed(file_id)
    try:
        os.remove(local_path)
    except OSError:
        pass

    return drafts


# ── Phase 1b: clips session ────────────────────────────────────────────────

def _process_clips_session(videos: list[dict]) -> int:
    """Download all clips → analyze each → cluster by person → compile and upload drafts."""
    print(f"\n{'='*60}")
    print(f"🎬 Clips session: {len(videos)} clip(s)")
    print(f"{'='*60}")

    clip_analyses: list[dict] = []
    for video_meta in videos:
        try:
            path = download_video(video_meta["id"], video_meta["name"])
        except Exception:
            logger.error("Skipping %s — download failed", video_meta["name"])
            continue
        analysis = analyze_session(path)
        clip_analyses.append({"path": path, "analysis": analysis})

    if not clip_analyses:
        print("⚠️ No clips downloaded — nothing to process")
        for v in videos:
            mark_as_processed(v["id"])
        return 0

    print(f"\n🔍 Clustering {len(clip_analyses)} clip(s) by person identity...")
    clusters = cluster_clips(clip_analyses)

    if not clusters:
        print("⚠️ No persons identified across clips")
        for ca in clip_analyses:
            try:
                os.remove(ca["path"])
            except OSError:
                pass
        for v in videos:
            mark_as_processed(v["id"])
        return 0

    print(f"👥 Found {len(clusters)} unique person(s)")

    drafts = 0
    for cluster in clusters:
        reel = compile_multi_source_reel(cluster["appearances"])
        if not reel:
            continue
        name = _safe_draft_name(cluster["description"])
        try:
            upload_draft(reel, name)
            drafts += 1
        except Exception:
            logger.error("Draft upload failed for %s", name)
        finally:
            try:
                os.remove(reel)
            except OSError:
                pass

    for ca in clip_analyses:
        try:
            os.remove(ca["path"])
        except OSError:
            pass

    for v in videos:
        mark_as_processed(v["id"])

    return drafts


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n🎬 D to R Pipeline — Phase 1: Ingest & Draft")
    print(f"📁 Tmp dir: {config.TMP_DIR}")

    new_videos = get_new_videos()
    if not new_videos:
        print("✅ No new videos — exiting")
        return

    mode = _classify_input(new_videos)
    print(f"📋 Mode: {mode} ({len(new_videos)} video(s))")

    if mode == "long_video":
        drafts = _process_long_video(new_videos[0])
    else:
        drafts = _process_clips_session(new_videos)

    if drafts:
        print(f"\n✅ {drafts} draft(s) uploaded to REVIEW folder")
        print("   Review in Drive, then run:  python deliver.py")
    else:
        print("\n⚠️ No drafts produced")

    logger.info("Phase 1 complete. Videos: %d, Drafts: %d", len(new_videos), drafts)


if __name__ == "__main__":
    main()

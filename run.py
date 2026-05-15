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
from concurrent.futures import ThreadPoolExecutor

import config
from pipeline.drive    import download_video, get_new_videos, mark_as_processed, upload_draft, record_failure
from pipeline.analyzer import analyze_session
from pipeline.editor   import create_reel, compile_multi_source_reel
from pipeline.identity import cluster_clips

_LARGE_FILE_BYTES  = 100_000_000   # 100 MB threshold
_MAX_DL_WORKERS    = min(4, config.MAX_CUT_WORKERS)
_MAX_UL_WORKERS    = 3             # cap to avoid Drive API quota exhaustion


# ── Helpers ────────────────────────────────────────────────────────────────

_FILENAME_SPORT_HINTS: dict[str, str] = {
    "surf":     "surfing",
    "swim":     "swimming",
    "skate":    "skateboarding",
    "ski":      "skiing",
    "snow":     "snowboarding",
    "football": "football",
    "soccer":   "soccer",
    "basket":   "basketball",
    "cycl":     "cycling",
    "moto":     "motocross",
    "parkour":  "parkour",
}


def _dominant_activity(clip_analyses: list[dict]) -> str:
    """Returns the most common activity; falls back to filename hint; never returns 'unknown'."""
    from collections import Counter
    counts: Counter = Counter()
    for ca in clip_analyses:
        act = ca.get("analysis", {}).get("activity", "")
        if act and act not in ("unknown", "other", "sport", ""):
            counts[act] += 1
    if counts:
        return counts.most_common(1)[0][0]
    for ca in clip_analyses:
        name = ca.get("meta", {}).get("name", "").lower()
        for kw, sport in _FILENAME_SPORT_HINTS.items():
            if kw in name:
                return sport
    return "sport"


def _classify_input(videos: list[dict]) -> str:
    """
    Classify the input batch:
      long_video   — single file > 100 MB (full game / session)
      mixed_session — multiple files where at least one is > 100 MB
      clips_session — multiple small files or single small file
    """
    def _size(v: dict) -> int:
        try:
            return int(v.get("size", "0"))
        except (ValueError, TypeError):
            return 0

    if len(videos) == 1:
        return "long_video" if _size(videos[0]) > _LARGE_FILE_BYTES else "clips_session"

    if any(_size(v) > _LARGE_FILE_BYTES for v in videos):
        return "mixed_session"

    return "clips_session"


def _safe_draft_name(description: str) -> str:
    """Create a filesystem-safe draft filename from a person description."""
    safe  = "".join(c if c.isalnum() or c in " _-" else "_" for c in description)
    safe  = safe.strip()[:50].strip()
    today = date.today().strftime("%Y%m%d")
    return f"DRAFT_{safe}_{today}.mp4"


def _compile_clusters(clusters: list[dict], activity: str) -> int:
    """Compile reels sequentially (CPU-bound), then upload in parallel (network-bound)."""
    pending: list[tuple[str, str]] = []
    for cluster in clusters:
        reels = compile_multi_source_reel(cluster["appearances"], sport=activity,
                                          athlete_label=cluster["description"])
        for reel_idx, reel in enumerate(reels):
            suffix = f" (part {reel_idx + 1})" if len(reels) > 1 else ""
            name   = _safe_draft_name(cluster["description"] + suffix)
            pending.append((reel, name))

    def _upload_one(args: tuple[str, str]) -> bool:
        reel_path, name = args
        try:
            upload_draft(reel_path, name)
            return True
        except Exception:
            logger.error("Draft upload failed for %s", name)
            return False
        finally:
            try: os.remove(reel_path)
            except OSError: pass

    if not pending:
        return 0
    workers = min(len(pending), _MAX_UL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_upload_one, pending))
    return sum(results)


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
        if record_failure(file_id):
            mark_as_processed(file_id)
        return 0

    try:
        session = analyze_session(local_path)
    except Exception:
        logger.error("Analysis failed for %s — will retry (up to 3 times)", filename)
        if record_failure(file_id):
            mark_as_processed(file_id)
        try:
            os.remove(local_path)
        except OSError:
            pass
        return 0

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
        reels = create_reel(local_path, person["events"], sport=activity,
                            athlete_label=person["description"])
        for reel_idx, reel in enumerate(reels):
            suffix = f" (part {reel_idx + 1})" if len(reels) > 1 else ""
            name   = _safe_draft_name(person["description"] + suffix)
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

def _download_one(video_meta: dict) -> dict | None:
    """Download one video; returns {path, meta} or None on failure."""
    try:
        path = download_video(video_meta["id"], video_meta["name"])
        return {"path": path, "meta": video_meta}
    except Exception:
        logger.error("Download failed for %s", video_meta["name"])
        if record_failure(video_meta["id"]):
            mark_as_processed(video_meta["id"])
        return None


def _process_clips_session(videos: list[dict]) -> int:
    """Download clips in parallel → analyze each → cluster by person → compile and upload."""
    print(f"\n{'='*60}")
    print(f"🎬 Clips session: {len(videos)} clip(s)")
    print(f"{'='*60}")

    # Parallel downloads (network-bound)
    workers = min(len(videos), _MAX_DL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        dl_results = list(pool.map(_download_one, videos))
    downloaded = [r for r in dl_results if r is not None]

    # Sequential analysis (Gemini rate-limited)
    clip_analyses: list[dict] = []
    for item in downloaded:
        try:
            analysis = analyze_session(item["path"])
        except Exception:
            logger.error("Analysis failed for %s — will retry (up to 3 times)", item["meta"]["name"])
            if record_failure(item["meta"]["id"]):
                mark_as_processed(item["meta"]["id"])
            try: os.remove(item["path"])
            except OSError: pass
            continue
        clip_analyses.append({"path": item["path"], "analysis": analysis, "meta": item["meta"]})

    if not clip_analyses:
        print("⚠️ No clips downloaded or analyzed — nothing to process")
        return 0

    activity = _dominant_activity(clip_analyses)

    print(f"\n🔍 Clustering {len(clip_analyses)} clip(s) by person identity...")
    clusters = cluster_clips(clip_analyses)

    if not clusters:
        print("⚠️ No persons identified across clips")
        for ca in clip_analyses:
            try:
                os.remove(ca["path"])
            except OSError:
                pass
            mark_as_processed(ca["meta"]["id"])
        return 0

    print(f"👥 Found {len(clusters)} unique person(s)")
    drafts = _compile_clusters(clusters, activity)

    for ca in clip_analyses:
        try:
            os.remove(ca["path"])
        except OSError:
            pass
        mark_as_processed(ca["meta"]["id"])

    return drafts


# ── Phase 1c: mixed session (long + short clips together) ──────────────────

def _process_mixed_session(videos: list[dict]) -> int:
    """
    Handles a batch that contains both long videos (>100 MB) and short clips.
    All files are analyzed with analyze_session; persons are clustered together
    across all sources so the long video and the short clips feed into the same reels.
    """
    long_videos  = [v for v in videos if _safe_size(v) > _LARGE_FILE_BYTES]
    short_clips  = [v for v in videos if _safe_size(v) <= _LARGE_FILE_BYTES]

    print(f"\n{'='*60}")
    print(f"🎬 Mixed session: {len(long_videos)} long + {len(short_clips)} short clip(s)")
    print(f"{'='*60}")

    for v in videos:
        label = "long" if _safe_size(v) > _LARGE_FILE_BYTES else "clip"
        print(f"  📥 [{label}] {v['name']}")

    # Parallel downloads (network-bound)
    workers = min(len(videos), _MAX_DL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        dl_results = list(pool.map(_download_one, videos))
    downloaded = [r for r in dl_results if r is not None]

    # Sequential analysis (Gemini rate-limited)
    clip_analyses: list[dict] = []
    for item in downloaded:
        try:
            analysis = analyze_session(item["path"])
        except Exception:
            logger.error("Analysis failed for %s — will retry (up to 3 times)", item["meta"]["name"])
            if record_failure(item["meta"]["id"]):
                mark_as_processed(item["meta"]["id"])
            try: os.remove(item["path"])
            except OSError: pass
            continue
        clip_analyses.append({"path": item["path"], "analysis": analysis, "meta": item["meta"]})

    if not clip_analyses:
        print("⚠️ No files downloaded — nothing to process")
        return 0

    activity = _dominant_activity(clip_analyses)

    print(f"\n🔍 Clustering {len(clip_analyses)} source(s) by person identity...")
    clusters = cluster_clips(clip_analyses)

    if not clusters:
        print("⚠️ No persons identified across sources")
        for ca in clip_analyses:
            try:
                os.remove(ca["path"])
            except OSError:
                pass
            mark_as_processed(ca["meta"]["id"])
        return 0

    print(f"👥 Found {len(clusters)} unique person(s)")
    drafts = _compile_clusters(clusters, activity)

    for ca in clip_analyses:
        try:
            os.remove(ca["path"])
        except OSError:
            pass
        mark_as_processed(ca["meta"]["id"])

    return drafts


def _safe_size(video: dict) -> int:
    try:
        return int(video.get("size", "0"))
    except (ValueError, TypeError):
        return 0


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
    elif mode == "mixed_session":
        drafts = _process_mixed_session(new_videos)
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

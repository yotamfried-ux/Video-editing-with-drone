"""
pipeline/orchestrator.py — Phase 1 pipeline business logic.
Scans Drive RAW folder → identifies persons → creates per-person reels → uploads to REVIEW.
"""

import json
import logging
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import config
from integrations.drive    import (download_video, get_new_videos, mark_as_processed,
                                    upload_draft, record_failure, flag_quality_issue)
from pipeline.stages.analyzer import analyze_session
from pipeline.stages.editor   import create_reel, compile_multi_source_reel, drain_quality_issues
from pipeline.stages.identity import cluster_clips
from pipeline.stages.feedback import get_stats as _feedback_stats
from integrations.ffmpeg      import get_source_info as _get_source_info

logger = logging.getLogger(__name__)

_LARGE_FILE_BYTES    = 100_000_000
_MAX_DL_WORKERS      = min(4, config.MAX_CUT_WORKERS)
_MAX_UL_WORKERS      = 3
_MAX_STAGED_ATTEMPTS = 5
_MIN_FREE_GB         = 5.0

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


def _run_reel_qa(reels: list[str], sport: str, athlete_label: str) -> None:
    """Run independent social-media QA on each non-music reel and log the result.

    Advisory only — never blocks upload. Reports verdict, engagement score,
    technical spec issues, and any weak content dimensions.
    """
    if not config.QA_REEL_CHECK:
        return
    from pipeline.stages.analyzer import qa_check_reel
    for reel in reels:
        if "_music" in os.path.basename(reel):
            continue
        qa      = qa_check_reel(reel, sport=sport, athlete_label=athlete_label)
        verdict = qa.get("verdict", "PASS")
        score   = qa.get("engagement_score", "?")
        overall = qa.get("overall", "")
        name    = Path(reel).name
        if verdict == "FAIL":
            tech_issues = qa.get("technical", {}).get("issues", [])
            weak = {k: v for k, v in qa.get("content", {}).items()
                    if isinstance(v, (int, float)) and v < 6}
            detail = []
            if tech_issues:
                detail.append(f"technical: {tech_issues}")
            if weak:
                detail.append(f"weak: {weak}")
            print(f"  ⚠️  Reel QA FAIL [{name}] engagement={score} — "
                  f"{'; '.join(detail) or overall}")
        else:
            print(f"  ✅ Reel QA PASS [{name}] engagement={score} — {overall}")


def _drain_and_flag(filename_to_file_id: dict[str, str]) -> None:
    from pipeline.stages.editor import drain_quality_issues
    issues = drain_quality_issues()
    if not issues:
        return
    by_video: dict[str, set[str]] = {}
    for issue in issues:
        by_video.setdefault(issue["video"], set()).add(issue["reason"])
    for video_name, reasons in by_video.items():
        file_id = filename_to_file_id.get(video_name)
        reason_str = ", ".join(sorted(reasons))
        if file_id:
            flag_quality_issue(file_id, reason_str)
        print(f"  ⚠️  Quality issues for '{video_name}': {reason_str}")


def _check_disk_space() -> None:
    free = shutil.disk_usage(config.TMP_DIR).free / (1024 ** 3)
    if free < _MIN_FREE_GB:
        raise RuntimeError(
            f"Insufficient disk space: {free:.1f} GB free in {config.TMP_DIR} "
            f"(need ≥{_MIN_FREE_GB} GB)"
        )


def _retry_pending_uploads() -> None:
    pending_dir = config.PENDING_UPLOADS_DIR
    if not os.path.isdir(pending_dir):
        return
    staged = [f for f in os.listdir(pending_dir) if f.endswith(".mp4")]
    if not staged:
        return
    print(f"\n📂 Retrying {len(staged)} staged reel(s) from previous run...")
    for filename in staged:
        reel_path  = os.path.join(pending_dir, filename)
        name_path  = reel_path + ".name"
        count_path = reel_path + ".attempts"
        try:
            attempts = int(open(count_path).read())
        except Exception:
            attempts = 0
        if attempts >= _MAX_STAGED_ATTEMPTS:
            logger.error("Staged reel '%s' failed %d time(s) — removing", filename, attempts)
            print(f"  ❌ Abandoned '{filename}' after {attempts} retries — deleted")
            for p in (reel_path, name_path, count_path):
                try: os.remove(p)
                except OSError: pass
            continue
        draft_name = open(name_path).read().strip() if os.path.exists(name_path) else filename
        try:
            upload_draft(reel_path, draft_name)
            for p in (reel_path, name_path, count_path):
                try: os.remove(p)
                except OSError: pass
            print(f"  ✅ Staged reel uploaded: {draft_name}")
        except Exception as exc:
            with open(count_path, "w") as f:
                f.write(str(attempts + 1))
            logger.warning("Staged reel still failing (%d/%d): %s — %s",
                           attempts + 1, _MAX_STAGED_ATTEMPTS, draft_name, exc)
            print(f"  ❌ Still failing ({attempts + 1}/{_MAX_STAGED_ATTEMPTS}): {draft_name}")


def _save_reel_metadata(draft_name: str, sport: str,
                        events: list[dict], source_quality: dict) -> None:
    try:
        meta_file = config.REEL_METADATA_FILE
        try:
            with open(meta_file) as f:
                metadata: dict = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            metadata = {}
        metadata[draft_name] = {
            "sport":          sport,
            "events":         [{"type": e.get("type", ""), "edit": e.get("edit", {})}
                                for e in events],
            "source_quality": source_quality,
        }
        tmp = meta_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        os.replace(tmp, meta_file)
    except Exception as e:
        logger.warning("Failed to save reel metadata for %s: %s", draft_name, e)


def _safe_draft_name(description: str) -> str:
    safe  = "".join(c if c.isalnum() or c in " _-" else "_" for c in description)
    safe  = safe.strip()[:50].strip()
    today = date.today().strftime("%Y%m%d")
    return f"DRAFT_{safe}_{today}.mp4"


def _dominant_activity(clip_analyses: list[dict]) -> str:
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


def _compile_clusters(clusters: list[dict], activity: str) -> int:
    pending: list[tuple[str, str]] = []
    pending_meta: list[tuple[str, str, list[dict], dict]] = []
    for cluster in clusters:
        first_path     = cluster["appearances"][0]["path"] if cluster["appearances"] else None
        source_quality = _get_source_info(first_path) if first_path else {}
        all_events     = [ev for app in cluster["appearances"] for ev in app.get("events", [])]
        events_out: list[tuple[str, list[dict]]] = []
        reels = compile_multi_source_reel(cluster["appearances"], sport=activity,
                                          athlete_label=cluster["description"],
                                          _events_out=events_out)
        _run_reel_qa(reels, sport=activity, athlete_label=cluster["description"])
        events_by_reel = {path: evs for path, evs in events_out}
        clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
        clean_idx   = 0
        for reel in reels:
            is_music = "_music" in os.path.basename(reel)
            if not is_music:
                clean_idx += 1
            part_label  = f" (part {clean_idx})" if clean_count > 1 else ""
            music_label = " (music)" if is_music else ""
            name        = _safe_draft_name(cluster["description"] + part_label + music_label)
            reel_events = events_by_reel.get(reel, all_events)
            pending.append((reel, name))
            pending_meta.append((reel, name, reel_events, source_quality))

    def _upload_one(args: tuple[str, str]) -> bool:
        reel_path, name = args
        try:
            upload_draft(reel_path, name)
            return True
        except Exception as exc:
            os.makedirs(config.PENDING_UPLOADS_DIR, exist_ok=True)
            staged = os.path.join(config.PENDING_UPLOADS_DIR, os.path.basename(reel_path))
            try:
                shutil.move(reel_path, staged)
                with open(staged + ".name", "w") as f:
                    f.write(name)
                logger.error("Upload failed for '%s' — staged at %s for next run", name, staged)
                print(f"⚠️  Upload failed — reel saved to pending_uploads/ for next run")
            except Exception:
                logger.error("Could not stage reel %s — reel lost: %s", reel_path, exc)
            return False
        finally:
            try:
                if os.path.exists(reel_path):
                    os.remove(reel_path)
            except OSError:
                pass

    if not pending:
        return 0
    workers = min(len(pending), _MAX_UL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_upload_one, pending))

    for (reel_path, name), ok, (_, _, events, src_q) in zip(pending, results, pending_meta):
        if ok:
            _save_reel_metadata(name, activity, events, src_q)

    return sum(results)


def _safe_size(video: dict) -> int:
    try:
        return int(video.get("size", "0"))
    except (ValueError, TypeError):
        return 0


def _download_one(video_meta: dict) -> dict | None:
    try:
        path = download_video(video_meta["id"], video_meta["name"])
        return {"path": path, "meta": video_meta}
    except Exception:
        logger.exception("Download failed for %s", video_meta["name"])
        if record_failure(video_meta["id"]):
            mark_as_processed(video_meta["id"])
        return None


def _process_long_video(video_meta: dict) -> int:
    file_id  = video_meta["id"]
    filename = video_meta["name"]
    print(f"\n{'='*60}")
    print(f"🎬 Long video: {filename}")
    print(f"{'='*60}")
    try:
        local_path = download_video(file_id, filename)
    except Exception:
        logger.exception("Skipping %s — download failed", filename)
        if record_failure(file_id):
            mark_as_processed(file_id)
        return 0
    try:
        session = analyze_session(local_path)
    except Exception:
        logger.exception("Analysis failed for %s — will retry (up to 3 times)", filename)
        if record_failure(file_id):
            mark_as_processed(file_id)
        try: os.remove(local_path)
        except OSError: pass
        return 0
    activity = session.get("activity", "sport")
    persons  = session.get("persons", [])
    if not persons:
        print(f"⚠️ No persons detected in '{filename}' — skipping")
        mark_as_processed(file_id)
        try: os.remove(local_path)
        except OSError: pass
        return 0
    print(f"👥 Detected {len(persons)} person(s): "
          f"{', '.join(p['description'][:30] for p in persons)}")
    source_quality = _get_source_info(local_path)
    _fn_to_id = {filename: file_id}
    drafts = 0
    for person in persons:
        if not person.get("events"):
            continue
        reels = create_reel(local_path, person["events"], sport=activity,
                            athlete_label=person["description"])
        _run_reel_qa(reels, sport=activity, athlete_label=person["description"])
        _drain_and_flag(_fn_to_id)
        clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
        clean_idx   = 0
        for reel in reels:
            is_music = "_music" in os.path.basename(reel)
            if not is_music:
                clean_idx += 1
            part_label  = f" (part {clean_idx})" if clean_count > 1 else ""
            music_label = " (music)" if is_music else ""
            name        = _safe_draft_name(person["description"] + part_label + music_label)
            try:
                upload_draft(reel, name)
                _save_reel_metadata(name, activity, person["events"], source_quality)
                drafts += 1
            except Exception:
                logger.exception("Draft upload failed for %s", name)
            finally:
                try: os.remove(reel)
                except OSError: pass
    mark_as_processed(file_id)
    try: os.remove(local_path)
    except OSError: pass
    return drafts


def _process_clips_session(videos: list[dict]) -> int:
    print(f"\n{'='*60}")
    print(f"🎬 Clips session: {len(videos)} clip(s)")
    print(f"{'='*60}")
    workers = min(len(videos), _MAX_DL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        dl_results = list(pool.map(_download_one, videos))
    downloaded = [r for r in dl_results if r is not None]
    clip_analyses: list[dict] = []
    for item in downloaded:
        try:
            analysis = analyze_session(item["path"])
        except Exception:
            logger.exception("Analysis failed for %s — will retry", item["meta"]["name"])
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
            try: os.remove(ca["path"])
            except OSError: pass
            mark_as_processed(ca["meta"]["id"])
        return 0
    print(f"👥 Found {len(clusters)} unique person(s)")
    drafts = _compile_clusters(clusters, activity)
    fn_to_id = {Path(ca["path"]).name: ca["meta"]["id"] for ca in clip_analyses}
    _drain_and_flag(fn_to_id)
    for ca in clip_analyses:
        try: os.remove(ca["path"])
        except OSError: pass
        mark_as_processed(ca["meta"]["id"])
    return drafts


def _process_mixed_session(videos: list[dict]) -> int:
    long_videos = [v for v in videos if _safe_size(v) > _LARGE_FILE_BYTES]
    short_clips = [v for v in videos if _safe_size(v) <= _LARGE_FILE_BYTES]
    print(f"\n{'='*60}")
    print(f"🎬 Mixed session: {len(long_videos)} long + {len(short_clips)} short clip(s)")
    print(f"{'='*60}")
    for v in videos:
        label = "long" if _safe_size(v) > _LARGE_FILE_BYTES else "clip"
        print(f"  📥 [{label}] {v['name']}")
    workers = min(len(videos), _MAX_DL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        dl_results = list(pool.map(_download_one, videos))
    downloaded = [r for r in dl_results if r is not None]
    clip_analyses: list[dict] = []
    for item in downloaded:
        try:
            analysis = analyze_session(item["path"])
        except Exception:
            logger.exception("Analysis failed for %s — will retry", item["meta"]["name"])
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
            try: os.remove(ca["path"])
            except OSError: pass
            mark_as_processed(ca["meta"]["id"])
        return 0
    print(f"👥 Found {len(clusters)} unique person(s)")
    drafts = _compile_clusters(clusters, activity)
    fn_to_id = {Path(ca["path"]).name: ca["meta"]["id"] for ca in clip_analyses}
    _drain_and_flag(fn_to_id)
    for ca in clip_analyses:
        try: os.remove(ca["path"])
        except OSError: pass
        mark_as_processed(ca["meta"]["id"])
    return drafts


def main() -> None:
    if "--feedback-stats" in sys.argv:
        stats = _feedback_stats()
        print("\n🏷️  Feedback database stats:")
        print(f"   Total approvals: {stats['total_approvals']}")
        for sport, count in sorted(stats["by_sport"].items()):
            print(f"   {sport}: {count} approval(s)")
        print(f"   Last approval: {stats['last_approval']}")
        return

    print("\n🎬 D to R Pipeline — Phase 1: Ingest & Draft")
    print(f"📁 Tmp dir: {config.TMP_DIR}")

    _retry_pending_uploads()
    _check_disk_space()

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

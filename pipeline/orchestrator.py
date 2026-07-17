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
from integrations.run_status import mark_run
from pipeline.stages.analyzer import analyze_session
from pipeline.stages.editor   import create_reel, compile_multi_source_reel, drain_quality_issues
from pipeline.stages.identity import cluster_clips
from pipeline.stages.feedback import get_stats as _feedback_stats
from integrations.ffmpeg      import get_source_info as _get_source_info

logger = logging.getLogger(__name__)

# Set to True by main() when pipeline exits with no new videos to process.
# run_tracked.py reads this flag to write no_input instead of succeeded.
no_input: bool = False

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


def _print_qa_result(reel: str, qa: dict) -> None:
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
    # Defects are printed for PASS too — minor issues are still worth a look.
    for d in qa.get("defects", []):
        sev  = str(d.get("severity", "minor")).upper()
        mark = "🔴" if sev == "CRITICAL" else "🟡"
        at   = d.get("at_seconds")
        at_s = f" @{at:.0f}s" if isinstance(at, (int, float)) else ""
        print(f"     {mark} {d.get('type', '?')}{at_s} — {d.get('note', '')}")


def _qa_blocking(qa: dict) -> bool:
    """A reel blocks on QA only for critical content defects — the class of
    problem the re-edit loop can actually fix by dropping/adjusting clips."""
    if qa.get("verdict") != "FAIL":
        return False
    return any(str(d.get("severity", "")).lower() == "critical"
               for d in qa.get("defects", []))


# Defect types fixed by REMOVING the offending clip from the timeline.
_DROP_DEFECTS = {"DUPLICATE_MOMENT", "IDENTITY_MISMATCH", "SOFT_FOCUS",
                 "NO_VISIBLE_ACTION", "DEAD_TIME", "LOW_QUALITY"}


from pipeline.rendered_timeline import (
    event_index_for_qa_defect as _event_index_for_qa_defect,
)


def _apply_qa_fixes(ordered_events: list[dict], defects: list[dict]) -> tuple[list[dict], bool]:
    """Translate QA defects into event-level edits.

    ordered_events is the reel timeline (including the cold-open teaser, which
    carries "_teaser": True). Defect timestamps are mapped to clips via estimated
    clip durations. Returns (fixed_events_without_teaser, changed) — the teaser
    is stripped because recompilation rebuilds it from the new climax.
    """
    # Rendered event offsets are persisted by the editor. Legacy metadata falls
    # back to source duration, but event IDs always take precedence.
    drop: set[int] = set()
    fixed = [dict(ev) for ev in ordered_events]
    changed = False
    n_real = sum(1 for ev in ordered_events if not ev.get("_teaser"))

    for d in defects:
        if str(d.get("severity", "")).lower() != "critical":
            continue
        dtype = str(d.get("type", "")).upper()
        at    = d.get("at_seconds")
        idx   = _event_index_for_qa_defect(fixed, d)

        if dtype == "BAD_FIRST_CLIP":
            idx = next((i for i, ev in enumerate(fixed) if not ev.get("_teaser")), None)
            if idx is not None and n_real - len(drop) > 1:
                drop.add(idx); changed = True
            continue
        if idx is None or fixed[idx].get("_teaser"):
            continue  # unmappable, or points at the intentional cold-open
        if dtype in _DROP_DEFECTS:
            if n_real - len(drop) > 1:   # never drop the last real clip
                drop.add(idx); changed = True
        elif dtype == "UNNATURAL_SLOWMO":
            edit = dict(fixed[idx].get("edit") or {})
            if edit.get("slowmo"):
                edit["slowmo"] = False
                fixed[idx]["edit"] = edit
                changed = True
        elif dtype == "PREMATURE_CUT":
            fixed[idx]["end"] = float(fixed[idx]["end"]) + 3.0  # clamped at cut time
            changed = True

    if not changed:
        return ordered_events, False
    result = [ev for i, ev in enumerate(fixed)
              if i not in drop and not ev.get("_teaser")]
    return result, bool(result)


def _qa_gate(reels: list[str], events_out: list, sport: str, athlete_label: str,
             recompile) -> tuple[list[str], dict, set[str]]:
    """QA every clean reel; critical FAILs trigger automatic re-edit + re-check.

    recompile(events, new_events_out) → list[str] rebuilds a reel (and its music
    sibling) from an adjusted event list. After config.QA_MAX_RETRIES the reel is
    kept but flagged so the draft name tells the operator it needs manual review.

    Returns (final_reels, events_by_reel, flagged_paths).
    """
    events_by_reel: dict = {p: evs for p, evs in events_out}
    flagged: set[str] = set()
    if not config.QA_REEL_CHECK or not reels:
        return reels, events_by_reel, flagged

    from pipeline.stages.analyzer import qa_check_reel
    final = list(reels)

    for reel in [r for r in reels if "_music" not in os.path.basename(r)]:
        _write_status("qa", 0.46, reel=Path(reel).name[:60],
                      athlete=str(athlete_label)[:60])
        qa = qa_check_reel(reel, sport=sport, athlete_label=athlete_label)
        _print_qa_result(reel, qa)
        cur, attempt = reel, 0

        while config.QA_GATE and _qa_blocking(qa) and attempt < config.QA_MAX_RETRIES:
            evs = events_by_reel.get(cur)
            if not evs:
                break
            fixed, ok = _apply_qa_fixes(evs, qa.get("defects", []))
            if not ok:
                print("  ⏭️  No actionable fix for QA defects — keeping reel as-is")
                break
            attempt += 1
            n_before = sum(1 for e in evs if not e.get("_teaser"))
            print(f"  🔁 QA re-edit {attempt}/{config.QA_MAX_RETRIES}: "
                  f"{n_before}→{len(fixed)} clip(s)")
            _write_status("qa", 0.47, reel=Path(cur).name[:60],
                          re_edit=f"{attempt}/{config.QA_MAX_RETRIES}")
            new_out: list = []
            try:
                new_reels = recompile(fixed, new_out)
            except Exception:
                logger.exception("QA re-edit recompile failed — keeping previous reel")
                break
            if not new_reels:
                break
            for p, e in new_out:
                events_by_reel[p] = e
            new_clean = next((r for r in new_reels
                              if "_music" not in os.path.basename(r)), None)
            if not new_clean:
                break
            # Swap old reel + its music sibling for the re-edited versions
            sibling = cur.replace(".mp4", "_music.mp4")
            for old in (cur, sibling):
                if old in final:
                    final.remove(old)
                if old not in new_reels and os.path.exists(old):
                    try: os.remove(old)
                    except OSError: pass
            final.extend(r for r in new_reels if r not in final)
            cur = new_clean
            qa = qa_check_reel(cur, sport=sport, athlete_label=athlete_label)
            _print_qa_result(cur, qa)

        if _qa_blocking(qa):
            flagged.add(cur)
            print(f"  🚩 QA still failing after {attempt} re-edit(s) — "
                  f"uploading FLAGGED for operator review")

    return final, events_by_reel, flagged


def _group_appearances(events: list[dict]) -> list[dict]:
    """Group _src-tagged events back into the appearances structure the
    multi-source compiler expects, preserving source order."""
    by_src: dict[str, list[dict]] = {}
    order: list[str] = []
    for ev in events:
        src = ev.get("_src")
        if not src:
            continue
        if src not in by_src:
            by_src[src] = []
            order.append(src)
        by_src[src].append({k: v for k, v in ev.items() if k != "_src"})
    return [{"path": src, "events": by_src[src]} for src in order]


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
    os.makedirs(config.TMP_DIR, exist_ok=True)  # fresh CI runners start without it
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
            "events":         [
                {
                    "type":        e.get("type", ""),
                    "score":       e.get("score", "?"),
                    "start":       e.get("start"),
                    "end":         e.get("end"),
                    "description": e.get("description", ""),
                    "edit":        e.get("edit", {}),
                }
                for e in events
            ],
            "source_quality": source_quality,
        }
        tmp = meta_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        os.replace(tmp, meta_file)
    except Exception as e:
        logger.warning("Failed to save reel metadata for %s: %s", draft_name, e)


def _record_draft_sources(draft_name: str, sources: list[dict],
                          sport: str, athlete_desc: str) -> None:
    """Persist draft → raw-source mapping in Supabase (CI runners are ephemeral;
    this is what makes operator 'reprocess this reel' possible later)."""
    try:
        from integrations.supabase_uploader import record_draft
        record_draft(draft_name, sources, sport, athlete_desc)
    except Exception as e:
        logger.debug("Draft source recording skipped (non-critical): %s", e)


def _handle_reprocess_requests() -> list[str]:
    """Consume operator reprocess requests from Supabase.

    For each pending request: re-queue the raw source video(s) (PROCESSED → RAW
    in Drive) and inject the operator's notes into this run's analysis prompts.
    Returns the operator-note keys created, so main() can clear them after the
    run (they are reprocess-specific and must not leak into future sessions).
    """
    try:
        from integrations.supabase_uploader import (fetch_pending_reprocess,
                                                    lookup_draft_sources,
                                                    mark_reprocess)
        requests = fetch_pending_reprocess()
    except Exception as e:
        logger.debug("Reprocess check skipped: %s", e)
        return []
    if not requests:
        return []

    from integrations.drive import requeue_video
    from pipeline.stages.feedback import record_operator_note
    print(f"\n🔁 {len(requests)} operator reprocess request(s) found")
    note_keys: list[str] = []
    for req in requests:
        req_id     = req.get("id", "")
        draft_name = req.get("draft_name", "") or ""
        notes      = (req.get("notes") or "").strip()
        sources    = lookup_draft_sources(draft_name) if draft_name else []
        requeued   = 0
        for src in sources:
            if src.get("id") and requeue_video(src["id"]):
                requeued += 1
        if requeued:
            print(f"  ↩️  '{draft_name}': {requeued} source video(s) re-queued")
            if notes:
                key = f"reprocess_{req_id[:8]}"
                record_operator_note(key, notes)
                note_keys.append(key)
            mark_reprocess(req_id, "queued")
        else:
            print(f"  ⚠️  '{draft_name}': source videos not found — cannot reprocess")
            mark_reprocess(req_id, "source_not_found")
    return note_keys


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


def _write_status(stage: str, progress: float, **meta) -> None:
    """Best-effort pipeline status update (visible live in the operator app)."""
    try:
        from integrations.supabase_uploader import write_pipeline_status
        write_pipeline_status(stage, progress, **meta)
    except Exception:
        pass


def _compile_clusters(clusters: list[dict], activity: str,
                      fn_to_id: dict[str, str] | None = None) -> int:
    pending: list[tuple[str, str]] = []
    pending_meta: list[tuple[str, str, list[dict], dict]] = []
    fn_to_id = fn_to_id or {}
    for ci, cluster in enumerate(clusters):
        _write_status("editing", 0.30 + 0.15 * (ci / max(1, len(clusters))),
                      cluster=f"{ci + 1}/{len(clusters)}",
                      athlete=str(cluster.get("description", ""))[:60])
        first_path     = cluster["appearances"][0]["path"] if cluster["appearances"] else None
        source_quality = _get_source_info(first_path) if first_path else {}
        all_events     = [ev for app in cluster["appearances"] for ev in app.get("events", [])]
        events_out: list[tuple[str, list[dict]]] = []
        reels = compile_multi_source_reel(cluster["appearances"], sport=activity,
                                          athlete_label=cluster["description"],
                                          _events_out=events_out)

        def _recompile(evs: list[dict], out: list) -> list[str]:
            return compile_multi_source_reel(_group_appearances(evs), sport=activity,
                                             athlete_label=cluster["description"],
                                             _events_out=out)

        reels, events_by_reel, flagged = _qa_gate(
            reels, events_out, activity, cluster["description"], _recompile)

        sources = [{"id": fn_to_id.get(Path(app["path"]).name, ""),
                    "name": Path(app["path"]).name}
                   for app in cluster["appearances"]]
        clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
        clean_idx   = 0
        for reel in reels:
            is_music = "_music" in os.path.basename(reel)
            if not is_music:
                clean_idx += 1
            part_label  = f" (part {clean_idx})" if clean_count > 1 else ""
            music_label = " (music)" if is_music else ""
            qa_label    = " QA-FLAGGED" if reel in flagged else ""
            name        = _safe_draft_name(cluster["description"] + part_label
                                           + music_label + qa_label)
            reel_events = events_by_reel.get(reel, all_events)
            pending.append((reel, name))
            pending_meta.append((reel, name, reel_events, source_quality))
            _record_draft_sources(name, sources, activity, cluster["description"])

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

    total = len(pending)
    for idx, ((reel_path, name), ok, (_, _, events, src_q)) in enumerate(
        zip(pending, results, pending_meta), start=1
    ):
        if ok:
            _save_reel_metadata(name, activity, events, src_q)
            try:
                from integrations.supabase_uploader import write_pipeline_status
                write_pipeline_status(
                    "uploading",
                    0.50 + 0.40 * (idx / total),
                    uploaded=idx,
                    total=total,
                    reel_name=name,
                )
            except Exception:
                pass

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
        events_out: list[tuple[str, list[dict]]] = []
        reels = create_reel(local_path, person["events"], sport=activity,
                            athlete_label=person["description"],
                            _events_out=events_out)

        def _recompile(evs: list[dict], out: list) -> list[str]:
            cleaned = [{k: v for k, v in ev.items() if k != "_src"} for ev in evs]
            return create_reel(local_path, cleaned, sport=activity,
                               athlete_label=person["description"], _events_out=out)

        reels, events_by_reel, flagged = _qa_gate(
            reels, events_out, activity, person["description"], _recompile)
        _drain_and_flag(_fn_to_id)
        clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
        clean_idx   = 0
        for reel in reels:
            is_music = "_music" in os.path.basename(reel)
            if not is_music:
                clean_idx += 1
            part_label  = f" (part {clean_idx})" if clean_count > 1 else ""
            music_label = " (music)" if is_music else ""
            qa_label    = " QA-FLAGGED" if reel in flagged else ""
            name        = _safe_draft_name(person["description"] + part_label
                                           + music_label + qa_label)
            reel_events = events_by_reel.get(reel, person["events"])
            try:
                upload_draft(reel, name)
                _save_reel_metadata(name, activity, reel_events, source_quality)
                _record_draft_sources(name, [{"id": file_id, "name": filename}],
                                      activity, person["description"])
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
    fn_to_id = {Path(ca["path"]).name: ca["meta"]["id"] for ca in clip_analyses}
    drafts = _compile_clusters(clusters, activity, fn_to_id)
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
    fn_to_id = {Path(ca["path"]).name: ca["meta"]["id"] for ca in clip_analyses}
    drafts = _compile_clusters(clusters, activity, fn_to_id)
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

    # Operator "send back for re-edit" requests: re-queue sources + inject notes
    reprocess_note_keys = _handle_reprocess_requests()

    new_videos = get_new_videos()
    if not new_videos:
        print("✅ No new videos — exiting")
        global no_input
        no_input = True
        mark_run(status="no_input", stage="no_input", progress=1.0)
        return

    from integrations.supabase_uploader import write_pipeline_status
    write_pipeline_status("downloading", 0.05, video_count=len(new_videos))

    mode = _classify_input(new_videos)
    print(f"📋 Mode: {mode} ({len(new_videos)} video(s))")

    write_pipeline_status("analyzing", 0.20, mode=mode)

    if mode == "long_video":
        drafts = _process_long_video(new_videos[0])
    elif mode == "mixed_session":
        drafts = _process_mixed_session(new_videos)
    else:
        drafts = _process_clips_session(new_videos)

    if drafts:
        write_pipeline_status("done", 1.0, drafts_created=drafts)
        print(f"\n✅ {drafts} draft(s) uploaded to REVIEW folder")
        print("   Review in Drive, then run:  python deliver.py")
    else:
        print("\n⚠️ No drafts produced")

    # Reprocess-specific operator notes were applied this run — clear them so
    # they don't leak into unrelated future sessions, and close the requests.
    if reprocess_note_keys:
        from pipeline.stages.feedback import clear_operator_note
        for key in reprocess_note_keys:
            clear_operator_note(key)
        try:
            from integrations.supabase_uploader import close_queued_reprocess
            close_queued_reprocess()
        except Exception:
            pass

    logger.info("Phase 1 complete. Videos: %d, Drafts: %d", len(new_videos), drafts)

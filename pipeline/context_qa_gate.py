"""Run-level context QA gate.

Evaluates all draft candidates in one run before upload and injects edit/source
context into reel QA so the judge sees the JSON decisions behind the draft.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_INSTALLED_FLAG = "_sportreel_context_qa_gate_installed"
_QA_WRAPPED = "_sportreel_context_qa_gate_wrapped_qa"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _src(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _fingerprint(event: dict[str, Any]) -> str:
    for key in ("event_fingerprint", "fingerprint", "visual_hash", "clip_hash"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _bucket_time(value: Any) -> int:
    return int(round(_num(value) * 2))


def event_window_key(event: dict[str, Any], index: int) -> tuple[Any, ...]:
    fp = _fingerprint(event)
    if fp:
        return ("fp", fp)
    source = _src(event)
    if source:
        return ("window", source, _bucket_time(event.get("start")), _bucket_time(event.get("end")), str(event.get("track_id") or ""))
    return ("event", _event_id(event, index), _bucket_time(event.get("start")), _bucket_time(event.get("end")))


def draft_fingerprint(events: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    return tuple(sorted(event_window_key(event, idx) for idx, event in enumerate(events) if not event.get("_teaser")))


def draft_quality(events: list[dict[str, Any]]) -> float:
    total = 0.0
    for event in events:
        if event.get("_teaser"):
            continue
        visible = max(0.0, min(1.0, _num(event.get("visible_ratio"), 1.0)))
        confidence = max(0.0, min(1.0, _num(event.get("perception_confidence"), _num(event.get("confidence"), 1.0))))
        total += _num(event.get("score")) + visible + confidence
    return total


def build_qa_package(reel_path: str, draft_name: str, events: list[dict[str, Any]], source_quality: dict[str, Any]) -> dict[str, Any]:
    return {"reel_path": reel_path, "draft_name": draft_name, "fingerprint": draft_fingerprint(events), "quality": draft_quality(events), "events": events, "source_quality": source_quality, "source_windows": [{"event_id": _event_id(event, idx), "source": _src(event), "start": event.get("start"), "end": event.get("end"), "final_cut_start": event.get("final_cut_start"), "final_cut_end": event.get("final_cut_end"), "track_id": event.get("track_id"), "fingerprint": _fingerprint(event)} for idx, event in enumerate(events) if not event.get("_teaser")]}


def build_edit_context(reel_path: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    windows = []
    for idx, event in enumerate(events or []):
        if event.get("_teaser"):
            continue
        windows.append({"event_id": _event_id(event, idx), "source": _src(event), "source_start": event.get("start"), "source_end": event.get("end"), "final_cut_start": event.get("final_cut_start"), "final_cut_end": event.get("final_cut_end"), "track_id": event.get("track_id"), "identity_gate": event.get("identity_gate"), "cut_window_status": event.get("cut_window_evidence_status"), "duplicate_evidence": event.get("dedup_dropped_duplicates", [])})
    return {"reel": reel_path, "source_windows": windows}


def _context_prompt(context: dict[str, Any]) -> str:
    compact = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return "\nEDIT_SOURCE_CONTEXT_JSON:\n" + compact + "\nJudge the final draft against these source windows: identity continuity, early cuts, and repeated source windows."


def _qa_gate_with_edit_context(orchestrator: Any, reels, events_out, sport, athlete_label, recompile):
    from pipeline.stages import analyzer
    context_by_reel = {reel: build_edit_context(reel, events) for reel, events in events_out}
    original_check = analyzer.qa_check_reel
    def contextual_check(reel, *args, **kwargs):
        ctx = context_by_reel.get(reel)
        if ctx:
            kwargs["athlete_label"] = str(kwargs.get("athlete_label", "")) + _context_prompt(ctx)
        return original_check(reel, *args, **kwargs)
    analyzer.qa_check_reel = contextual_check
    try:
        return orchestrator._qa_gate(reels, events_out, sport, athlete_label, recompile)
    finally:
        analyzer.qa_check_reel = original_check


def _duplicate_detail(dropped: dict[str, Any], kept: dict[str, Any]) -> dict[str, Any]:
    return {"reason": "duplicate_rendered_draft", "defect_type": "DUPLICATE_DRAFT", "blocking": True, "dropped_draft": dropped["draft_name"], "kept_draft": kept["draft_name"], "dropped_source_windows": dropped["source_windows"], "kept_source_windows": kept["source_windows"]}


def _attach_duplicate_detail(events: list[dict[str, Any]], detail: dict[str, Any]) -> list[dict[str, Any]]:
    if not events:
        return events
    first = {**events[0], "dedup_dropped_duplicates": [*(events[0].get("dedup_dropped_duplicates", []) or []), detail]}
    return [first, *events[1:]]


def filter_duplicate_draft_candidates(pending: list[tuple[str, str]], pending_meta: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]]) -> tuple[list[tuple[str, str]], list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]], list[dict[str, Any]]]:
    packages = [build_qa_package(reel, name, events, src_q) for reel, name, events, src_q in pending_meta]
    keep_by_fp: dict[tuple[tuple[Any, ...], ...], int] = {}
    dropped: list[dict[str, Any]] = []
    for idx, package in enumerate(packages):
        fp = package["fingerprint"]
        if not fp:
            keep_by_fp[(('empty', idx),)] = idx
        elif fp not in keep_by_fp:
            keep_by_fp[fp] = idx
        else:
            kept_idx = keep_by_fp[fp]
            kept = packages[kept_idx]
            if package["quality"] > kept["quality"]:
                dropped.append(_duplicate_detail(kept, package))
                keep_by_fp[fp] = idx
            else:
                dropped.append(_duplicate_detail(package, kept))
    kept_indices = set(keep_by_fp.values())
    by_kept_name: dict[str, list[dict[str, Any]]] = {}
    for detail in dropped:
        by_kept_name.setdefault(detail["kept_draft"], []).append(detail)
    filtered_pending: list[tuple[str, str]] = []
    filtered_meta: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]] = []
    for idx, meta in enumerate(pending_meta):
        if idx not in kept_indices:
            continue
        reel, name, events, src_q = meta
        for detail in by_kept_name.get(name, []):
            events = _attach_duplicate_detail(events, detail)
        filtered_pending.append(pending[idx])
        filtered_meta.append((reel, name, events, src_q))
    return filtered_pending, filtered_meta, dropped


def _patch_orchestrator(orchestrator: Any) -> None:
    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return
    def compile_clusters_with_context_qa(clusters: list[dict], activity: str, fn_to_id: dict[str, str] | None = None) -> int:
        try:
            from pipeline.real_identity_gate import enforce_identity_gate
            clusters = enforce_identity_gate(clusters)
        except Exception:
            pass
        pending: list[tuple[str, str]] = []
        pending_meta: list[tuple[str, str, list[dict], dict]] = []
        fn_to_id = fn_to_id or {}
        for ci, cluster in enumerate(clusters):
            orchestrator._write_status("editing", 0.30 + 0.15 * (ci / max(1, len(clusters))), cluster=f"{ci + 1}/{len(clusters)}", athlete=str(cluster.get("description", ""))[:60])
            first_path = cluster["appearances"][0]["path"] if cluster.get("appearances") else None
            source_quality = orchestrator._get_source_info(first_path) if first_path else {}
            all_events = [ev for app in cluster.get("appearances", []) for ev in app.get("events", [])]
            events_out: list[tuple[str, list[dict]]] = []
            reels = orchestrator.compile_multi_source_reel(cluster.get("appearances", []), sport=activity, athlete_label=cluster.get("description", ""), _events_out=events_out)
            def _recompile(evs: list[dict], out: list) -> list[str]:
                return orchestrator.compile_multi_source_reel(orchestrator._group_appearances(evs), sport=activity, athlete_label=cluster.get("description", ""), _events_out=out)
            reels, events_by_reel, flagged = _qa_gate_with_edit_context(orchestrator, reels, events_out, activity, cluster.get("description", ""), _recompile)
            sources = [{"id": fn_to_id.get(Path(app["path"]).name, ""), "name": Path(app["path"]).name} for app in cluster.get("appearances", [])]
            clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
            clean_idx = 0
            for reel in reels:
                is_music = "_music" in os.path.basename(reel)
                if not is_music:
                    clean_idx += 1
                part_label = f" (part {clean_idx})" if clean_count > 1 else ""
                music_label = " (music)" if is_music else ""
                qa_label = " QA-FLAGGED" if reel in flagged else ""
                name = orchestrator._safe_draft_name(str(cluster.get("description", "")) + part_label + music_label + qa_label)
                reel_events = events_by_reel.get(reel, all_events)
                pending.append((reel, name))
                pending_meta.append((reel, name, reel_events, source_quality))
                orchestrator._record_draft_sources(name, sources, activity, str(cluster.get("description", "")))
        pending, pending_meta, dropped = filter_duplicate_draft_candidates(pending, pending_meta)
        for detail in dropped:
            print(f"  Context QA blocked duplicate draft {detail['dropped_draft']} -> kept {detail['kept_draft']}")
        def _upload_one(args: tuple[str, str]) -> bool:
            reel_path, name = args
            try:
                orchestrator.upload_draft(reel_path, name)
                return True
            except Exception as exc:
                os.makedirs(orchestrator.config.PENDING_UPLOADS_DIR, exist_ok=True)
                staged = os.path.join(orchestrator.config.PENDING_UPLOADS_DIR, os.path.basename(reel_path))
                try:
                    orchestrator.shutil.move(reel_path, staged)
                    with open(staged + ".name", "w") as f:
                        f.write(name)
                    orchestrator.logger.error("Upload failed for '%s' — staged at %s for next run", name, staged)
                    print("Upload failed — reel saved to pending_uploads/ for next run")
                except Exception:
                    orchestrator.logger.error("Could not stage reel %s — reel lost: %s", reel_path, exc)
                return False
            finally:
                try:
                    if os.path.exists(reel_path):
                        os.remove(reel_path)
                except OSError:
                    pass
        if not pending:
            return 0
        workers = min(len(pending), orchestrator._MAX_UL_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_upload_one, pending))
        total = len(pending)
        for idx, ((_, name), ok, (_, _, events, src_q)) in enumerate(zip(pending, results, pending_meta), start=1):
            if ok:
                orchestrator._save_reel_metadata(name, activity, events, src_q)
                try:
                    from integrations.supabase_uploader import write_pipeline_status
                    write_pipeline_status("uploading", 0.50 + 0.40 * (idx / total), uploaded=idx, total=total, reel_name=name)
                except Exception:
                    pass
        return sum(results)
    orchestrator._compile_clusters = compile_clusters_with_context_qa
    setattr(orchestrator, _INSTALLED_FLAG, True)


def _wrap_existing_hook() -> bool:
    policy = sys.modules.get("pipeline.qa_gate_policy")
    if policy is None or getattr(policy, _QA_WRAPPED, False):
        return False
    original = getattr(policy, "_patch_orchestrator", None)
    if original is None:
        return False
    def patch_both(orchestrator: Any) -> None:
        original(orchestrator)
        _patch_orchestrator(orchestrator)
    policy._patch_orchestrator = patch_both
    setattr(policy, _QA_WRAPPED, True)
    return True


def install() -> None:
    module = sys.modules.get("pipeline.orchestrator")
    if module is not None:
        _patch_orchestrator(module)
        return
    if _wrap_existing_hook():
        return
    import pipeline.qa_gate_policy as policy
    policy.install()
    _wrap_existing_hook()

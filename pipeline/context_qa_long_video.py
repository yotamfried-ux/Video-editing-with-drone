"""Context QA for long-video person drafts."""
from __future__ import annotations

import os
import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_context_qa_long_video_installed"
_QA_WRAPPED = "_sportreel_context_qa_long_video_wrapped_qa"


def _with_src(events_out, local_path: str):
    return [(reel, [{**event, "_src": local_path, "source": event.get("source") or local_path} for event in events]) for reel, events in events_out]


def _patch_orchestrator(orchestrator: Any) -> None:
    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return

    def process_long_video_with_context_qa(video_meta: dict) -> int:
        from pipeline.context_qa_gate import filter_duplicate_draft_candidates, _qa_gate_with_edit_context
        file_id = video_meta["id"]
        filename = video_meta["name"]
        try:
            local_path = orchestrator.download_video(file_id, filename)
        except Exception:
            orchestrator.logger.exception("Skipping %s — download failed", filename)
            if orchestrator.record_failure(file_id):
                orchestrator.mark_as_processed(file_id)
            return 0
        try:
            session = orchestrator.analyze_session(local_path)
        except Exception:
            orchestrator.logger.exception("Analysis failed for %s", filename)
            if orchestrator.record_failure(file_id):
                orchestrator.mark_as_processed(file_id)
            try: os.remove(local_path)
            except OSError: pass
            return 0
        activity = session.get("activity", "sport")
        persons = session.get("persons", [])
        if not persons:
            orchestrator.mark_as_processed(file_id)
            try: os.remove(local_path)
            except OSError: pass
            return 0
        source_quality = orchestrator._get_source_info(local_path)
        pending: list[tuple[str, str]] = []
        pending_meta: list[tuple[str, str, list[dict], dict]] = []
        name_sources: dict[str, tuple[str, list[dict], str, str]] = {}
        for person in persons:
            if not person.get("events"):
                continue
            events_out: list[tuple[str, list[dict]]] = []
            reels = orchestrator.create_reel(local_path, person["events"], sport=activity, athlete_label=person.get("description", ""), _events_out=events_out)
            events_out = _with_src(events_out, local_path)
            def _recompile(evs: list[dict], out: list) -> list[str]:
                cleaned = [{k: v for k, v in ev.items() if k != "_src"} for ev in evs]
                result = orchestrator.create_reel(local_path, cleaned, sport=activity, athlete_label=person.get("description", ""), _events_out=out)
                out[:] = _with_src(out, local_path)
                return result
            reels, events_by_reel, flagged = _qa_gate_with_edit_context(orchestrator, reels, events_out, activity, person.get("description", ""), _recompile)
            clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
            clean_idx = 0
            for reel in reels:
                is_music = "_music" in os.path.basename(reel)
                if not is_music:
                    clean_idx += 1
                part_label = f" (part {clean_idx})" if clean_count > 1 else ""
                music_label = " (music)" if is_music else ""
                qa_label = " QA-FLAGGED" if reel in flagged else ""
                name = orchestrator._safe_draft_name(person.get("description", "") + part_label + music_label + qa_label)
                reel_events = [{**event, "_src": local_path, "source": event.get("source") or local_path} for event in events_by_reel.get(reel, person["events"])]
                pending.append((reel, name))
                pending_meta.append((reel, name, reel_events, source_quality))
                name_sources[name] = (name, [{"id": file_id, "name": filename}], activity, person.get("description", ""))
        pending, pending_meta, dropped = filter_duplicate_draft_candidates(pending, pending_meta)
        for detail in dropped:
            print(f"  Context QA blocked duplicate long-video draft {detail['dropped_draft']} -> kept {detail['kept_draft']}")
        drafts = 0
        for reel, name in pending:
            events = next((m[2] for m in pending_meta if m[0] == reel and m[1] == name), [])
            try:
                orchestrator.upload_draft(reel, name)
                orchestrator._save_reel_metadata(name, activity, events, source_quality)
                args = name_sources.get(name)
                if args:
                    orchestrator._record_draft_sources(*args)
                drafts += 1
            except Exception:
                orchestrator.logger.exception("Draft upload failed for %s", name)
            finally:
                try: os.remove(reel)
                except OSError: pass
        orchestrator.mark_as_processed(file_id)
        try: os.remove(local_path)
        except OSError: pass
        return drafts

    orchestrator._process_long_video = process_long_video_with_context_qa
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

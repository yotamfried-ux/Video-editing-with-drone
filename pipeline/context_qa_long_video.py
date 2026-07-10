"""Context QA for long-video person drafts."""
from __future__ import annotations

from collections import Counter
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

_INSTALLED_FLAG = "_sportreel_context_qa_long_video_installed"
_QA_WRAPPED = "_sportreel_context_qa_long_video_wrapped_qa"
_FILTER_TRACE_FILE = "selection_filter_events.json"
_MIN_CLEAN_SUBWINDOW_SEC = 6.0
_MAX_CLEAN_SUBWINDOW_SEC = 15.0
_OTHER_SUBJECT_PADDING_SEC = 0.35
_PRIMARY_PADDING_SEC = 0.2
_MIN_PRIMARY_DETECTIONS_FOR_RESCUE = 4

_RUNTIME_EVENT_KEYS = {
    "_src",
    "source",
    "qa_gate",
    "multi_person_clip_gate",
    "subject_isolation_gate",
    "identity_gate",
    "dedup_dropped_duplicates",
}
_ID_FIELDS_TO_CLEAR = {
    "visible_track_ids",
    "nearby_track_ids",
    "source_window_track_ids",
    "all_visible_track_ids",
    "visible_person_ids",
    "nearby_person_ids",
    "source_window_person_ids",
    "all_visible_person_ids",
    "other_track_ids",
    "other_person_ids",
    "secondary_track_ids",
    "secondary_person_ids",
}


def _with_src(events_out, local_path: str):
    return [(reel, [{**event, "_src": local_path, "source": event.get("source") or local_path} for event in events]) for reel, events in events_out]


def _stage_reel_candidate(reel_path: str, tmp_dir: str, index: int, draft_name: str) -> str | None:
    """Snapshot a rendered long-video candidate before the next person overwrites it."""
    if not os.path.exists(reel_path):
        return None
    os.makedirs(tmp_dir, exist_ok=True)
    stem = Path(reel_path).stem
    staged = os.path.join(tmp_dir, f"{stem}.draft-candidate-{index:03d}.mp4")
    counter = 1
    while os.path.exists(staged):
        staged = os.path.join(tmp_dir, f"{stem}.draft-candidate-{index:03d}-{counter:02d}.mp4")
        counter += 1
    shutil.copy2(reel_path, staged)
    return staged


def _cleanup_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _annotate_subject_gates(events: list[dict[str, Any]], local_path: str, athlete_label: str) -> list[dict[str, Any]]:
    from pipeline.multi_person_clip_gate import annotate_multi_person_events
    from pipeline.subject_gate_policy import annotate_subject_events

    sourced = [{**event, "_src": local_path, "source": event.get("source") or local_path} for event in events]
    annotated = annotate_subject_events(sourced, source_video=local_path, athlete_label=athlete_label)
    return annotate_multi_person_events(annotated, athlete_label)


def _has_subject_gate_defect(events: list[dict[str, Any]]) -> bool:
    from pipeline.multi_person_clip_gate import has_multi_person_defect
    from pipeline.subject_gate_policy import has_subject_isolation_defect

    return has_multi_person_defect(events) or has_subject_isolation_defect(events)


def _strip_runtime_event_keys(event: dict[str, Any]) -> dict[str, Any]:
    """Remove QA/runtime-only annotations before handing an event back to editor."""
    return {key: value for key, value in event.items() if key not in _RUNTIME_EVENT_KEYS}


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_key(event: dict[str, Any]) -> tuple[float | None, float | None, str, str]:
    start = _num(event.get("start"))
    end = _num(event.get("end"))
    return (
        None if start is None else round(start, 2),
        None if end is None else round(end, 2),
        str(event.get("type") or event.get("event_type") or ""),
        str(event.get("description") or "")[:160],
    )


def _event_window(event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start")
    end = event.get("end")
    try:
        duration = round(float(end) - float(start), 2)
    except (TypeError, ValueError):
        duration = event.get("duration")
    return {"start": start, "end": end, "duration": duration}


def _track_id_from_detection(detection: Any) -> str | None:
    value = getattr(detection, "tracker_id", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("track_id") or detection.get("tracker_id")
    return None if value is None else str(value)


def _time_from_detection(detection: Any) -> float | None:
    value = getattr(detection, "time_sec", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("time_sec")
    return _num(value)


def _detection_source(detection: Any) -> str:
    value = getattr(detection, "source_video", None)
    if value is None and isinstance(detection, dict):
        value = detection.get("source_video") or detection.get("_source_video")
    return str(value or "")


def _source_name(value: Any) -> str:
    return Path(str(value or "")).name


def _sources_match(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left) == str(right) or _source_name(left) == _source_name(right)


def _load_sidecar_detections(local_path: str) -> list[Any]:
    try:
        from pipeline.perception.runtime import load_sidecar_detections
    except Exception:
        return []
    try:
        return list(load_sidecar_detections(local_path) or [])
    except Exception:
        return []


def _primary_track_id(event: dict[str, Any]) -> str | None:
    for gate_key in ("subject_isolation_gate", "multi_person_clip_gate"):
        gate = event.get(gate_key)
        if not isinstance(gate, dict):
            continue
        value = gate.get("primary_track_id") or gate.get("primary_subject_id")
        if value:
            text = str(value)
            return text.split("track_id:", 1)[1] if text.startswith("track_id:") else text
    value = event.get("track_id")
    return None if value is None else str(value)


def _detections_in_event(event: dict[str, Any], local_path: str) -> list[Any]:
    start = _num(event.get("start"))
    end = _num(event.get("end"))
    if start is None or end is None or end <= start:
        return []
    out: list[Any] = []
    for detection in _load_sidecar_detections(local_path):
        det_source = _detection_source(detection)
        if det_source and not _sources_match(det_source, local_path):
            continue
        time_sec = _time_from_detection(detection)
        if time_sec is None:
            continue
        if start <= time_sec <= end:
            out.append(detection)
    return out


def _best_clean_subwindow(event: dict[str, Any], local_path: str) -> dict[str, Any] | None:
    """Find a clean 6s+ single-track sub-window inside a multi-person event.

    The production failure was not that no surf moments existed; the model often
    returned broad wave windows where an extra surfer appeared only briefly. This
    rescue uses the perception sidecar to cut the event down to a clean section
    where the blocked event's primary track is the only detected subject.
    """
    primary = _primary_track_id(event)
    if not primary:
        return None
    event_start = _num(event.get("start"))
    event_end = _num(event.get("end"))
    if event_start is None or event_end is None or event_end - event_start < _MIN_CLEAN_SUBWINDOW_SEC:
        return None

    rows = _detections_in_event(event, local_path)
    if not rows:
        return None
    primary_times = sorted(
        time_sec
        for detection in rows
        for time_sec in [_time_from_detection(detection)]
        if time_sec is not None and _track_id_from_detection(detection) == primary
    )
    if len(primary_times) < _MIN_PRIMARY_DETECTIONS_FOR_RESCUE:
        return None

    other_times = sorted(
        time_sec
        for detection in rows
        for time_sec in [_time_from_detection(detection)]
        if time_sec is not None and _track_id_from_detection(detection) not in {None, primary}
    )

    segments: list[tuple[float, float]] = []
    segment_start = event_start
    for other_time in other_times:
        left = other_time - _OTHER_SUBJECT_PADDING_SEC
        right = other_time + _OTHER_SUBJECT_PADDING_SEC
        if left - segment_start >= _MIN_CLEAN_SUBWINDOW_SEC:
            segments.append((segment_start, left))
        segment_start = max(segment_start, right)
    if event_end - segment_start >= _MIN_CLEAN_SUBWINDOW_SEC:
        segments.append((segment_start, event_end))

    best: dict[str, Any] | None = None
    for segment_start, segment_end in segments:
        in_segment = [time_sec for time_sec in primary_times if segment_start <= time_sec <= segment_end]
        if len(in_segment) < _MIN_PRIMARY_DETECTIONS_FOR_RESCUE:
            continue
        clean_start = max(segment_start, in_segment[0] - _PRIMARY_PADDING_SEC)
        clean_end = min(segment_end, in_segment[-1] + _PRIMARY_PADDING_SEC)
        if clean_end - clean_start > _MAX_CLEAN_SUBWINDOW_SEC:
            clean_end = clean_start + _MAX_CLEAN_SUBWINDOW_SEC
        duration = clean_end - clean_start
        if duration < _MIN_CLEAN_SUBWINDOW_SEC:
            continue
        candidate = {
            "start": round(clean_start, 2),
            "end": round(clean_end, 2),
            "duration": round(duration, 2),
            "primary_track_id": primary,
            "primary_detection_count": len([time_sec for time_sec in in_segment if clean_start <= time_sec <= clean_end]),
            "original_window": _event_window(event),
            "excluded_other_track_count": len(set(_track_id_from_detection(item) for item in rows if _track_id_from_detection(item) not in {None, primary})),
        }
        if best is None or (candidate["duration"], candidate["primary_detection_count"]) > (best["duration"], best["primary_detection_count"]):
            best = candidate
    return best


def _remove_identity_fields(event: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        key: value
        for key, value in event.items()
        if key not in _ID_FIELDS_TO_CLEAR and key not in _RUNTIME_EVENT_KEYS
    }
    cleaned.pop("final_cut_start", None)
    cleaned.pop("final_cut_end", None)
    return cleaned


def _rescue_event_if_possible(event: dict[str, Any], local_path: str) -> dict[str, Any]:
    if not _has_subject_gate_defect([event]):
        return event
    subwindow = _best_clean_subwindow(event, local_path)
    if not subwindow:
        return {
            **event,
            "selection_rescue": {
                "attempted": True,
                "status": "no_clean_subwindow_found",
                "min_clean_subwindow_sec": _MIN_CLEAN_SUBWINDOW_SEC,
            },
        }

    rescued = _remove_identity_fields(event)
    rescued.update({
        "start": subwindow["start"],
        "end": subwindow["end"],
        "duration": subwindow["duration"],
        "final_cut_start": subwindow["start"],
        "final_cut_end": subwindow["end"],
        "track_id": subwindow["primary_track_id"],
        "selection_rescue": {
            "attempted": True,
            "status": "clean_subwindow_rescued",
            "rescue_stage": "clean_subwindow_rescue",
            **subwindow,
        },
    })
    return rescued


def _gate_reason_codes(event: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for gate_key in ("multi_person_clip_gate", "subject_isolation_gate"):
        gate = event.get(gate_key)
        if not isinstance(gate, dict):
            continue
        defect = gate.get("defect")
        if isinstance(defect, dict) and defect.get("type"):
            code = str(defect.get("type"))
            if code not in codes:
                codes.append(code)
        decision = str(gate.get("decision") or "").lower()
        if decision in {"review_required", "blocked", "fail", "failed"} and "MULTI_PERSON_CLIP" not in codes:
            codes.append("MULTI_PERSON_CLIP")
    rescue = event.get("selection_rescue")
    if isinstance(rescue, dict) and rescue.get("status") == "no_clean_subwindow_found":
        if "NO_CLEAN_SUBWINDOW_FOUND" not in codes:
            codes.append("NO_CLEAN_SUBWINDOW_FOUND")
    if not codes and _has_subject_gate_defect([event]):
        codes.append("SUBJECT_GATE")
    return codes


def _read_filter_trace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "sportreel.selection_filter_events.v1", "records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "sportreel.selection_filter_events.v1", "records": []}
    if not isinstance(payload, dict):
        return {"schema_version": "sportreel.selection_filter_events.v1", "records": []}
    records = payload.get("records")
    if not isinstance(records, list):
        payload["records"] = []
    payload.setdefault("schema_version", "sportreel.selection_filter_events.v1")
    return payload


def _append_filter_trace(
    *,
    local_path: str,
    athlete_label: str,
    annotated: list[dict[str, Any]],
    deduped: list[dict[str, Any]],
) -> None:
    """Persist event-level pre-render decisions for later selection audit."""
    try:
        import config
    except Exception:
        return

    path = Path(config.TMP_DIR) / _FILTER_TRACE_FILE
    payload = _read_filter_trace(path)
    records = [item for item in payload.get("records", []) if isinstance(item, dict)]

    remaining_passes = Counter(_event_key(event) for event in deduped)
    for event in annotated:
        key = _event_key(event)
        subject_blocked = _has_subject_gate_defect([event])
        gate_codes = _gate_reason_codes(event) if subject_blocked else []
        rescue = event.get("selection_rescue") if isinstance(event.get("selection_rescue"), dict) else {}
        if subject_blocked:
            selected_for_render = False
            discarded = True
            discard_stage = "long_video_pre_qa_prefilter"
            discard_cause = "no_clean_subwindow_found" if rescue.get("status") == "no_clean_subwindow_found" else "subject_gated_by_pre_qa_prefilter"
        elif remaining_passes[key] > 0:
            remaining_passes[key] -= 1
            selected_for_render = True
            discarded = False
            discard_stage = None
            discard_cause = None
        else:
            selected_for_render = False
            discarded = True
            discard_stage = "long_video_pre_qa_prefilter"
            discard_cause = "duplicate_source_window_before_render"
            gate_codes = ["DUPLICATE_SOURCE_WINDOW"]

        records.append({
            "source_video": Path(local_path).name,
            "source_path": local_path,
            "person_description": athlete_label,
            "event_type": str(event.get("type") or event.get("event_type") or ""),
            "score": event.get("score"),
            "source_window": _event_window(event),
            "description": event.get("description", ""),
            "selected_for_render": selected_for_render,
            "discarded": discarded,
            "discard_stage": discard_stage,
            "discard_cause": discard_cause,
            "reason_codes": gate_codes,
            "selection_rescue": rescue or None,
            "subject_isolation_gate": event.get("subject_isolation_gate"),
            "multi_person_clip_gate": event.get("multi_person_clip_gate"),
        })

    payload["records"] = records
    payload["record_count"] = len(records)
    payload["selected_for_render_count"] = sum(1 for item in records if item.get("selected_for_render"))
    payload["discarded_count"] = sum(1 for item in records if item.get("discarded"))
    payload["clean_subwindow_rescue_count"] = sum(
        1
        for item in records
        if isinstance(item.get("selection_rescue"), dict)
        and item["selection_rescue"].get("status") == "clean_subwindow_rescued"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        a_start, a_end = float(a.get("start", 0.0)), float(a.get("end", 0.0))
        b_start, b_end = float(b.get("start", 0.0)), float(b.get("end", 0.0))
    except (TypeError, ValueError):
        return 0.0
    overlap = min(a_end, b_end) - max(a_start, b_start)
    if overlap <= 0:
        return 0.0
    shortest = max(0.1, min(a_end - a_start, b_end - b_start))
    return overlap / shortest


def _dedupe_render_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one source window per physical moment before rendering."""
    scored = sorted(
        enumerate(events),
        key=lambda item: (float(item[1].get("score", 0) or 0), float(item[1].get("end", 0) or 0) - float(item[1].get("start", 0) or 0)),
        reverse=True,
    )
    keep: list[tuple[int, dict[str, Any]]] = []
    for original_index, event in scored:
        if any(_overlap_ratio(event, kept) > 0.35 for _, kept in keep):
            continue
        keep.append((original_index, event))
    return [event for _, event in sorted(keep, key=lambda item: item[0])]


def _prepare_events_for_render(events: list[dict[str, Any]], local_path: str, athlete_label: str) -> tuple[list[dict[str, Any]], int, int]:
    """Reject or rescue known QA-blocking windows before render/upload."""
    initially_annotated = _annotate_subject_gates(events or [], local_path, athlete_label)
    rescued_inputs = [_rescue_event_if_possible(event, local_path) for event in initially_annotated]
    annotated = _annotate_subject_gates([_strip_runtime_event_keys(event) for event in rescued_inputs], local_path, athlete_label)
    clean = [event for event in annotated if not _has_subject_gate_defect([event])]
    blocked_count = len(annotated) - len(clean)
    deduped = _dedupe_render_events(clean)
    duplicate_count = len(clean) - len(deduped)
    _append_filter_trace(local_path=local_path, athlete_label=athlete_label, annotated=annotated, deduped=deduped)
    return [_strip_runtime_event_keys(event) for event in deduped], blocked_count, duplicate_count


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
            try:
                os.remove(local_path)
            except OSError:
                pass
            return 0
        activity = session.get("activity", "sport")
        persons = session.get("persons", [])
        if not persons:
            orchestrator.mark_as_processed(file_id)
            try:
                os.remove(local_path)
            except OSError:
                pass
            return 0
        source_quality = orchestrator._get_source_info(local_path)
        pending: list[tuple[str, str]] = []
        pending_meta: list[tuple[str, str, list[dict], dict]] = []
        name_sources: dict[str, tuple[str, list[dict], str, str]] = {}
        staged_reels: set[str] = set()
        produced_reels: set[str] = set()
        for person in persons:
            if not person.get("events"):
                continue
            athlete_label = str(person.get("description", ""))
            render_events, blocked_count, duplicate_count = _prepare_events_for_render(person.get("events", []), local_path, athlete_label)
            if blocked_count:
                print(f"  🧹 Pre-QA skipped {blocked_count} subject-gated event(s) for {athlete_label[:60]}")
            if duplicate_count:
                print(f"  🧹 Pre-QA skipped {duplicate_count} duplicate source-window event(s) for {athlete_label[:60]}")
            if not render_events:
                print(f"  ⏭️  No clean single-athlete events for {athlete_label[:60]} — no draft uploaded")
                continue
            events_out: list[tuple[str, list[dict]]] = []
            reels = orchestrator.create_reel(local_path, render_events, sport=activity, athlete_label=athlete_label, _events_out=events_out)
            produced_reels.update(reels or [])
            events_out = [(reel, _annotate_subject_gates(events, local_path, athlete_label)) for reel, events in _with_src(events_out, local_path)]

            def _recompile(evs: list[dict], out: list) -> list[str]:
                cleaned = [_strip_runtime_event_keys(event) for event in evs]
                result = orchestrator.create_reel(local_path, cleaned, sport=activity, athlete_label=athlete_label, _events_out=out)
                produced_reels.update(result or [])
                out[:] = [(reel, _annotate_subject_gates(events, local_path, athlete_label)) for reel, events in _with_src(out, local_path)]
                return result

            reels, events_by_reel, flagged = _qa_gate_with_edit_context(orchestrator, reels, events_out, activity, athlete_label, _recompile)
            produced_reels.update(reels or [])
            flagged_set = set(flagged or [])
            clean_count = sum(1 for r in reels if "_music" not in os.path.basename(r))
            clean_idx = 0
            for reel in reels:
                produced_reels.add(reel)
                is_music = "_music" in os.path.basename(reel)
                if not is_music:
                    clean_idx += 1
                part_label = f" (part {clean_idx})" if clean_count > 1 else ""
                music_label = " (music)" if is_music else ""
                raw_events = events_by_reel.get(reel, render_events)
                reel_events = _annotate_subject_gates(raw_events, local_path, athlete_label)
                events_by_reel[reel] = reel_events
                if _has_subject_gate_defect(reel_events):
                    flagged_set.add(reel)
                qa_label = " QA-FLAGGED" if reel in flagged_set else ""
                name = orchestrator._safe_draft_name(person.get("description", "") + part_label + music_label + qa_label)
                staged_reel = _stage_reel_candidate(reel, os.path.dirname(reel) or orchestrator.config.TMP_DIR, len(pending), name)
                if not staged_reel:
                    orchestrator.logger.warning("Skipping draft candidate %s — rendered file missing before staging: %s", name, reel)
                    continue
                pending.append((staged_reel, name))
                pending_meta.append((staged_reel, name, reel_events, source_quality))
                staged_reels.add(staged_reel)
                name_sources[name] = (name, [{"id": file_id, "name": filename}], activity, person.get("description", ""))
        pending, pending_meta, dropped = filter_duplicate_draft_candidates(pending, pending_meta)
        kept_reels = {reel for reel, _ in pending}
        for staged in staged_reels - kept_reels:
            _cleanup_file(staged)
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
                _cleanup_file(reel)
        for reel in produced_reels - kept_reels:
            _cleanup_file(reel)
        orchestrator.mark_as_processed(file_id)
        try:
            os.remove(local_path)
        except OSError:
            pass
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

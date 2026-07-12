"""Runtime hook that emits selector candidates and removes duplicate source windows.

Raw model timestamps are recovered before both analyzer filtering and selector
classification, so rendered actions and diagnostic candidates share one event set.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import config
from pipeline.chunk_timeline_runtime import merge_selector_payloads, source_duration
from pipeline.raw_timestamp_recovery import enrich_selector_payload, recover_raw_session_payload
from pipeline.source_window_dedup import dedupe_session
from pipeline.stages.selector_candidates import build_selector_candidate_events, write_selector_candidate_events

logger = logging.getLogger(__name__)
_OUTPUT_NAME = "selector_candidate_events.json"


def _read_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "sportreel.selector_candidate_events.v1", "candidates": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "sportreel.selector_candidate_events.v1", "candidates": []}
    return payload if isinstance(payload, dict) else {"schema_version": "sportreel.selector_candidate_events.v1", "candidates": []}


def _merge_counter_summaries(summaries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for summary in summaries:
        values = summary.get(key)
        if not isinstance(values, dict):
            continue
        for name, count in values.items():
            try:
                counter[str(name)] += int(count)
            except (TypeError, ValueError):
                continue
    return dict(counter)


def _append_payload(path: Path, payload: dict[str, Any]) -> None:
    existing = _read_existing(path)
    candidates = [item for item in existing.get("candidates", []) if isinstance(item, dict)]
    candidates.extend(item for item in payload.get("candidates", []) if isinstance(item, dict))
    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded_count = sum(1 for item in candidates if item.get("discarded"))
    summaries = [
        item for item in [existing.get("chunk_timeline_summary"), payload.get("chunk_timeline_summary")]
        if isinstance(item, dict)
    ]
    merged_summary = {
        "source_duration_sec": next((item.get("source_duration_sec") for item in reversed(summaries) if item.get("source_duration_sec") is not None), None),
        "chunk_count": sum(int(item.get("chunk_count") or 0) for item in summaries),
        "person_ids_namespaced": any(bool(item.get("person_ids_namespaced")) for item in summaries),
        "invalid_timestamp_candidate_count": sum(int(item.get("invalid_timestamp_candidate_count") or 0) for item in summaries),
        "clamped_timestamp_candidate_count": sum(int(item.get("clamped_timestamp_candidate_count") or 0) for item in summaries),
        "minute_second_recovered_candidate_count": sum(int(item.get("minute_second_recovered_candidate_count") or 0) for item in summaries),
        "timestamp_basis_counts": _merge_counter_summaries(summaries, "timestamp_basis_counts"),
        "timestamp_encoding_counts": _merge_counter_summaries(summaries, "timestamp_encoding_counts"),
    }
    merged = {
        "schema_version": "sportreel.selector_candidate_events.v1",
        "source_video": payload.get("source_video") or existing.get("source_video"),
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": discarded_count,
        "discard_causes_available": discarded_count > 0 and all(item.get("discard_cause") for item in candidates if item.get("discarded")),
        "chunk_timeline_summary": merged_summary,
        "candidates": candidates,
    }
    write_selector_candidate_events(path, merged)


def install() -> None:
    """Patch analyzer.analyze_session to emit normalized selector diagnostics."""
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, "_sportreel_selector_candidate_runtime_installed", False):
        return

    original_analyze_session = analyzer.analyze_session
    # raw_timestamp_recovery.install() must run first; this captured parser is the
    # recovery-aware wrapper and therefore feeds the same events to the pipeline.
    original_parse_session = analyzer._parse_session

    def analyze_session_with_selector_candidates(video_path: str) -> dict:
        captured_payloads: list[dict[str, Any]] = []
        source_video = Path(video_path).name

        def parse_and_capture(raw_text: str) -> dict:
            try:
                recovered = recover_raw_session_payload(raw_text, float(config.MIN_EVENT_SEC))
                candidate_payload = build_selector_candidate_events(
                    [person for person in recovered.get("persons", []) if isinstance(person, dict)],
                    source_video=source_video,
                    min_event_sec=float(config.MIN_EVENT_SEC),
                    score_threshold=6,
                    dedup_start_seconds=2.0,
                )
                captured_payloads.append(enrich_selector_payload(candidate_payload, recovered))
            except Exception as exc:
                logger.warning("Selector candidate capture failed: %s", exc)
            return original_parse_session(raw_text)

        analyzer._parse_session = parse_and_capture
        try:
            result = original_analyze_session(video_path)
        finally:
            analyzer._parse_session = original_parse_session

        result = dedupe_session(result, default_source=source_video)
        dropped_count = result.get("diagnostics", {}).get("source_window_dedup_dropped_count", 0)
        if dropped_count:
            logger.warning("Dropped %d duplicate source-window event(s) before reel selection", dropped_count)

        if captured_payloads:
            try:
                duration = source_duration(video_path)
            except Exception:
                duration = float(len(captured_payloads)) * float(getattr(analyzer, "_CHUNK_MAX_MINUTES", 8)) * 60.0
            path = Path(config.TMP_DIR) / _OUTPUT_NAME
            payload = merge_selector_payloads(
                captured_payloads,
                source_video=source_video,
                segment_sec=float(getattr(analyzer, "_CHUNK_MAX_MINUTES", 8)) * 60.0,
                source_duration_sec=duration,
            )
            _append_payload(path, payload)
            logger.info(
                "Wrote selector candidate events: %d selected, %d discarded, %d recovered MM.SS, %d invalid timestamps -> %s",
                payload.get("selected_count", 0),
                payload.get("discarded_count", 0),
                payload.get("chunk_timeline_summary", {}).get("minute_second_recovered_candidate_count", 0),
                payload.get("chunk_timeline_summary", {}).get("invalid_timestamp_candidate_count", 0),
                path,
            )
        return result

    analyzer.analyze_session = analyze_session_with_selector_candidates
    analyzer._sportreel_selector_candidate_runtime_installed = True

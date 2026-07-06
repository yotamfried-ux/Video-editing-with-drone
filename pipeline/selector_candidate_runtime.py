"""Runtime hook that emits selector candidate events from analyzer parsing.

The tracked Actions entrypoint installs this before importing the orchestrator.
It captures Gemini's raw person/events payload before analyzer filtering, mirrors the
existing selector policy, and writes `/tmp/dtor/selector_candidate_events.json`
for diagnostics without changing the analyzer return value.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import config
from pipeline.stages.selector_candidates import build_selector_candidate_events, write_selector_candidate_events

logger = logging.getLogger(__name__)
_OUTPUT_NAME = "selector_candidate_events.json"


def _parse_raw_session(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _shift_candidate(candidate: dict[str, Any], offset: float) -> dict[str, Any]:
    if offset <= 0:
        return dict(candidate)
    shifted = dict(candidate)
    window = dict(shifted.get("source_window") or {})
    for key in ("start", "end"):
        if isinstance(window.get(key), (int, float)):
            window[key] = round(float(window[key]) + offset, 2)
    if isinstance(window.get("start"), (int, float)) and isinstance(window.get("end"), (int, float)):
        window["duration"] = round(float(window["end"]) - float(window["start"]), 2)
    shifted["source_window"] = window
    return shifted


def _merge_payloads(payloads: list[dict[str, Any]], source_video: str, seg_secs: float) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for idx, payload in enumerate(payloads):
        offset = idx * seg_secs if len(payloads) > 1 else 0.0
        for raw in payload.get("candidates", []) or []:
            if isinstance(raw, dict):
                candidate = _shift_candidate(raw, offset)
                candidate["source_video"] = source_video
                candidates.append(candidate)
    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded_count = sum(1 for item in candidates if item.get("discarded"))
    return {
        "schema_version": "sportreel.selector_candidate_events.v1",
        "source_video": source_video,
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": discarded_count,
        "discard_causes_available": discarded_count > 0 and all(item.get("discard_cause") for item in candidates if item.get("discarded")),
        "candidates": candidates,
    }


def _read_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "sportreel.selector_candidate_events.v1", "candidates": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "sportreel.selector_candidate_events.v1", "candidates": []}
    return payload if isinstance(payload, dict) else {"schema_version": "sportreel.selector_candidate_events.v1", "candidates": []}


def _append_payload(path: Path, payload: dict[str, Any]) -> None:
    existing = _read_existing(path)
    candidates = [item for item in existing.get("candidates", []) if isinstance(item, dict)]
    candidates.extend(item for item in payload.get("candidates", []) if isinstance(item, dict))
    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded_count = sum(1 for item in candidates if item.get("discarded"))
    merged = {
        "schema_version": "sportreel.selector_candidate_events.v1",
        "source_video": payload.get("source_video") or existing.get("source_video"),
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": discarded_count,
        "discard_causes_available": discarded_count > 0 and all(item.get("discard_cause") for item in candidates if item.get("discarded")),
        "candidates": candidates,
    }
    write_selector_candidate_events(path, merged)


def install() -> None:
    """Patch analyzer.analyze_session to emit selector candidate diagnostics."""
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, "_sportreel_selector_candidate_runtime_installed", False):
        return

    original_analyze_session = analyzer.analyze_session
    original_parse_session = analyzer._parse_session

    def analyze_session_with_selector_candidates(video_path: str) -> dict:
        captured_payloads: list[dict[str, Any]] = []
        source_video = Path(video_path).name

        def parse_and_capture(raw_text: str) -> dict:
            try:
                raw = _parse_raw_session(raw_text)
                captured_payloads.append(build_selector_candidate_events(
                    [person for person in raw.get("persons", []) if isinstance(person, dict)],
                    source_video=source_video,
                    min_event_sec=float(config.MIN_EVENT_SEC),
                    score_threshold=6,
                    dedup_start_seconds=2.0,
                ))
            except Exception as exc:
                logger.warning("Selector candidate capture failed: %s", exc)
            return original_parse_session(raw_text)

        analyzer._parse_session = parse_and_capture
        try:
            result = original_analyze_session(video_path)
        finally:
            analyzer._parse_session = original_parse_session

        if captured_payloads:
            path = Path(config.TMP_DIR) / _OUTPUT_NAME
            payload = _merge_payloads(captured_payloads, source_video, float(getattr(analyzer, "_CHUNK_MAX_MINUTES", 8)) * 60.0)
            _append_payload(path, payload)
            logger.info(
                "Wrote selector candidate events: %d selected, %d discarded -> %s",
                payload.get("selected_count", 0),
                payload.get("discarded_count", 0),
                path,
            )
        return result

    analyzer.analyze_session = analyze_session_with_selector_candidates
    analyzer._sportreel_selector_candidate_runtime_installed = True

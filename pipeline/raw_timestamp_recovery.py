"""Recover compact MM.SS model timestamps before analyzer fragment filtering.

The production analyzer prompt asks for seconds, but run 29194242123 returned
values such as ``7.39`` to mean 7:39. ``analyzer._parse_session`` normally drops
such values as sub-second fragments before chunk normalization can inspect them.
This runtime recovers only otherwise-unusable windows and preserves raw evidence.
"""
from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

_INSTALL_FLAG = "_sportreel_raw_timestamp_recovery_installed"
_CHUNK_BRIDGE_FLAG = "_sportreel_raw_timestamp_chunk_bridge_installed"
_TIMESTAMP_FIELDS = (
    "timestamp_encoding",
    "timestamp_recovered",
    "raw_chunk_start",
    "raw_chunk_end",
    "interpreted_chunk_start",
    "interpreted_chunk_end",
)


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _minute_second_value(value: float) -> float | None:
    if value < 0:
        return None
    minutes = int(math.floor(value + 1e-9))
    seconds = int(round((value - minutes) * 100))
    if seconds < 0 or seconds >= 60:
        return None
    return float(minutes * 60 + seconds)


def _parse_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def recover_event_timestamp(event: dict[str, Any], min_event_sec: float) -> dict[str, Any]:
    """Return an event with deterministic encoding evidence and optional MM.SS recovery."""
    recovered = dict(event)
    raw_start = _num(event.get("start"))
    raw_end = _num(event.get("end"))
    if raw_start is None or raw_end is None or raw_end <= raw_start:
        return recovered

    encoding = "decimal_seconds"
    interpreted_start = raw_start
    interpreted_end = raw_end
    used_recovery = False
    if raw_end - raw_start < min_event_sec:
        minute_start = _minute_second_value(raw_start)
        minute_end = _minute_second_value(raw_end)
        if (
            minute_start is not None
            and minute_end is not None
            and minute_end - minute_start >= min_event_sec
        ):
            encoding = "minute_second"
            interpreted_start = minute_start
            interpreted_end = minute_end
            used_recovery = True
            recovered["start"] = round(interpreted_start, 3)
            recovered["end"] = round(interpreted_end, 3)

    recovered.update({
        "timestamp_encoding": encoding,
        "timestamp_recovered": used_recovery,
        "raw_chunk_start": round(raw_start, 3),
        "raw_chunk_end": round(raw_end, 3),
        "interpreted_chunk_start": round(interpreted_start, 3),
        "interpreted_chunk_end": round(interpreted_end, 3),
    })
    return recovered


def recover_raw_session_payload(raw_text: str, min_event_sec: float) -> dict[str, Any]:
    """Parse and recover all person events without mutating the raw response object."""
    payload = copy.deepcopy(_parse_payload(raw_text))
    for person in payload.get("persons", []) or []:
        if not isinstance(person, dict):
            continue
        person["events"] = [
            recover_event_timestamp(event, min_event_sec)
            for event in person.get("events", []) or []
            if isinstance(event, dict)
        ]
    return payload


def _event_key(event: dict[str, Any]) -> tuple[str, float | None, float | None, str]:
    return (
        str(event.get("type") or "highlight"),
        _num(event.get("start")),
        _num(event.get("end")),
        str(event.get("description") or "")[:160],
    )


def annotate_parsed_session(parsed: dict[str, Any], recovered_payload: dict[str, Any]) -> dict[str, Any]:
    """Reattach recovery evidence after the core parser filters/sorts events."""
    evidence_by_person: dict[str, dict[tuple[str, float | None, float | None, str], dict[str, Any]]] = {}
    for person in recovered_payload.get("persons", []) or []:
        if not isinstance(person, dict):
            continue
        person_id = str(person.get("id") or "person_?")
        evidence_by_person[person_id] = {
            _event_key(event): event
            for event in person.get("events", []) or []
            if isinstance(event, dict)
        }

    out = copy.deepcopy(parsed)
    for person in out.get("persons", []) or []:
        if not isinstance(person, dict):
            continue
        lookup = evidence_by_person.get(str(person.get("id") or "person_?"), {})
        for event in person.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            source = lookup.get(_event_key(event))
            if source:
                for field in _TIMESTAMP_FIELDS:
                    if source.get(field) is not None:
                        event[field] = source[field]
    return out


def enrich_selector_payload(payload: dict[str, Any], recovered_payload: dict[str, Any]) -> dict[str, Any]:
    """Attach raw/interpreted timestamp evidence to selector candidates."""
    lookup: dict[tuple[str, str, float | None, float | None, str], dict[str, Any]] = {}
    for person in recovered_payload.get("persons", []) or []:
        if not isinstance(person, dict):
            continue
        person_id = str(person.get("id") or "person_?")
        for event in person.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            event_type, start, end, description = _event_key(event)
            lookup[(person_id, event_type, start, end, description)] = event

    enriched = copy.deepcopy(payload)
    for candidate in enriched.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        window = candidate.get("source_window") if isinstance(candidate.get("source_window"), dict) else {}
        key = (
            str(candidate.get("person_id") or "person_?"),
            str(candidate.get("event_type") or "highlight"),
            _num(window.get("start")),
            _num(window.get("end")),
            str(candidate.get("description") or "")[:160],
        )
        source = lookup.get(key)
        if not source:
            continue
        candidate.update({
            "timestamp_encoding": source.get("timestamp_encoding"),
            "timestamp_recovered": bool(source.get("timestamp_recovered")),
            "raw_timestamp_window": {
                "start": source.get("raw_chunk_start"),
                "end": source.get("raw_chunk_end"),
            },
            "interpreted_timestamp_window": {
                "start": source.get("interpreted_chunk_start"),
                "end": source.get("interpreted_chunk_end"),
            },
        })
    return enriched


def _install_chunk_evidence_bridge() -> None:
    import pipeline.chunk_timeline_runtime as chunk_runtime

    if getattr(chunk_runtime, _CHUNK_BRIDGE_FLAG, False):
        return

    original_normalize = chunk_runtime._normalize_event
    original_merge_selector = chunk_runtime.merge_selector_payloads

    def normalize_with_recovery_evidence(event, **kwargs):
        normalized, evidence = original_normalize(event, **kwargs)
        if normalized is not None:
            for field in _TIMESTAMP_FIELDS:
                if event.get(field) is not None:
                    normalized[field] = event[field]
        return normalized, evidence

    def merge_selector_with_recovery_evidence(payloads, **kwargs):
        result = original_merge_selector(payloads, **kwargs)
        original_candidates = [
            candidate
            for payload in payloads
            for candidate in payload.get("candidates", []) or []
            if isinstance(candidate, dict)
        ]
        output_candidates = [
            candidate for candidate in result.get("candidates", []) or [] if isinstance(candidate, dict)
        ]
        for output, source in zip(output_candidates, original_candidates):
            if source.get("timestamp_encoding") is None:
                continue
            output["timestamp_encoding"] = source.get("timestamp_encoding")
            output["timestamp_recovered"] = bool(source.get("timestamp_recovered"))
            output["raw_timestamp_window"] = source.get("raw_timestamp_window")
            output["interpreted_timestamp_window"] = source.get("interpreted_timestamp_window")
        summary = result.setdefault("chunk_timeline_summary", {})
        recovered_count = sum(1 for item in output_candidates if item.get("timestamp_recovered"))
        summary["minute_second_recovered_candidate_count"] = recovered_count
        encoding_counts: dict[str, int] = {}
        for item in output_candidates:
            encoding = str(item.get("timestamp_encoding") or "unknown")
            encoding_counts[encoding] = encoding_counts.get(encoding, 0) + 1
        summary["timestamp_encoding_counts"] = encoding_counts
        return result

    chunk_runtime._normalize_event = normalize_with_recovery_evidence
    chunk_runtime.merge_selector_payloads = merge_selector_with_recovery_evidence
    setattr(chunk_runtime, _CHUNK_BRIDGE_FLAG, True)


def install() -> None:
    import config
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, _INSTALL_FLAG, False):
        return
    original_parse = analyzer._parse_session

    def parse_with_timestamp_recovery(raw_text: str) -> dict[str, Any]:
        recovered_payload = recover_raw_session_payload(raw_text, float(config.MIN_EVENT_SEC))
        parsed = original_parse(json.dumps(recovered_payload, ensure_ascii=False))
        return annotate_parsed_session(parsed, recovered_payload)

    analyzer._parse_session = parse_with_timestamp_recovery
    setattr(analyzer, _INSTALL_FLAG, True)
    _install_chunk_evidence_bridge()

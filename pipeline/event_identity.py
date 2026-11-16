"""A canonical, source-scoped id for every candidate event, assigned when the event is created.

Run 43725044948: 0 of 25 EDL shots carried an event id. The diagnostics inferred lineage from source and
window, which breaks as soon as a later stage revises the window. The id is fixed at creation from what the
analyzer said (source file, person, original window, type), stored on the event with that original window, and
carried unchanged through refinement, ordering, rendering and the EDL.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

UID_KEY = "event_uid"
ORIGIN_KEY = "event_uid_origin"
ANALYZER = "analyzer"
LATE = "assigned_late"
RESCUE = "rescue"


UID_SCHEMA = "v2"
_SOURCE_REF_CACHE: dict[str, tuple[str, str]] = {}
# Every id computed in this process (one pipeline run) and the key it was computed from. A second, different
# event that would compute an already issued id (a late event with the same window, type and track as another)
# gets a salted id instead of silently sharing it.
_ISSUED: dict[str, str] = {}


def reset_for_tests() -> None:
    _ISSUED.clear()
    _SOURCE_REF_CACHE.clear()


def source_ref(source: str) -> tuple[str, str]:
    """(kind, value) naming the source video: its content SHA-256, or its file name when it cannot be read.

    Two files with the same name are different sources, and one file under two names is the same source.
    """
    key = os.path.abspath(str(source or ""))
    if key not in _SOURCE_REF_CACHE:
        try:
            from pipeline.edl_export import source_sha256

            _SOURCE_REF_CACHE[key] = ("sha256", source_sha256(key))
        except Exception:  # noqa: BLE001 - unreadable or absent file
            _SOURCE_REF_CACHE[key] = ("name", os.path.basename(key))
    return _SOURCE_REF_CACHE[key]


def compute_event_uid(source: str, person_id: str, local_key: str) -> str:
    """Id from the source's content, the person and a key that is unique inside that person's events.

    No timestamp takes part, so two events whose rounded windows coincide stay distinct and a revised window
    cannot change the id.
    """
    kind, value = source_ref(source)
    payload = "|".join([UID_SCHEMA, kind, value, str(person_id or ""), str(local_key)])
    return f"ev{UID_SCHEMA[1:]}_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def ensure_event_uid(event: dict[str, Any], source: str, person_id: str = "", *, origin: str = ANALYZER,
                     local_key: str | None = None) -> str:
    """Give the event its id once. An event that already has one keeps it, whatever its window is now."""
    existing = event.get(UID_KEY)
    if existing:
        return str(existing)
    given = event.get("event_id") or event.get("id")
    if given:
        # An id set upstream is the canonical one; never replace it.
        event[UID_KEY] = str(given)
        event.setdefault(ORIGIN_KEY, "provided")
        return str(given)
    if local_key is None:
        # An event created after analysis has no ordinal: its own exact window, type and track name it.
        local_key = "late|{!r}|{!r}|{}|{}".format(
            event.get("start"), event.get("end"), event.get("type"), event.get("track_id"))
    person = person_id or str(event.get("person_id") or "")
    uid = compute_event_uid(source, person, local_key)
    issued_key = f"{source_ref(source)}|{person}|{local_key}"
    if origin != ANALYZER:
        # Analyzer ids are keyed by ordinal and are the same on a re-run by design. A late event's key is its
        # window; two distinct late events can share it, so each one after the first gets a counter.
        n = 1
        while uid in _ISSUED:
            n += 1
            uid = compute_event_uid(source, person, f"{local_key}|n{n}")
    _ISSUED.setdefault(uid, issued_key)
    event[UID_KEY] = uid
    event[ORIGIN_KEY] = origin
    event["event_uid_schema"] = UID_SCHEMA
    event["event_source_ref"] = ":".join(source_ref(source))
    event.setdefault("event_id", uid)
    # The window the analyzer gave, so a revised window can always be traced back.
    event.setdefault("analyzer_window", {"start": event.get("start"), "end": event.get("end")})
    return uid


def assign_session_event_uids(session: dict[str, Any], source: str) -> int:
    """Assign ids to every event of an analyzed session. Returns how many events now carry one."""
    count = 0
    for person in (session or {}).get("persons", []) or []:
        ordinal = 0
        for event in person.get("events", []) or []:
            if isinstance(event, dict):
                ordinal += 1
                ensure_event_uid(event, source, str(person.get("id") or ""), local_key=f"ordinal|{ordinal}")
                count += 1
    return count


def lineage_issues(events: list[dict[str, Any]]) -> list[str]:
    """Provenance problems in the events of one reel: an event without a canonical id, or two shots of one reel
    claiming the same id. Teasers are excluded (they repeat a moment on purpose and are never published)."""
    issues: list[str] = []
    seen: set[str] = set()
    for event in events or []:
        if not isinstance(event, dict) or event.get("_teaser"):
            continue
        uid = event.get(UID_KEY) or event.get("event_id")
        if not uid:
            issues.append("missing_event_provenance")
            continue
        if str(uid) in seen:
            issues.append("duplicate_event_uid")
        seen.add(str(uid))
    return sorted(set(issues))

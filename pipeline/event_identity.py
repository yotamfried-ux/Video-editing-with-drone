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


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "na"


def compute_event_uid(source: str, person_id: str, start: Any, end: Any, event_type: Any) -> str:
    payload = "|".join([
        os.path.basename(str(source or "")), str(person_id or ""), _fmt(start), _fmt(end), str(event_type or ""),
    ])
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def ensure_event_uid(event: dict[str, Any], source: str, person_id: str = "", *, origin: str = ANALYZER) -> str:
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
    uid = compute_event_uid(source, person_id or str(event.get("person_id") or ""), event.get("start"), event.get("end"), event.get("type"))
    event[UID_KEY] = uid
    event[ORIGIN_KEY] = origin
    event.setdefault("event_id", uid)
    # The window the id was computed from, so a revised window can always be traced back.
    event.setdefault("analyzer_window", {"start": event.get("start"), "end": event.get("end")})
    return uid


def assign_session_event_uids(session: dict[str, Any], source: str) -> int:
    """Assign ids to every event of an analyzed session. Returns how many events now carry one."""
    count = 0
    for person in (session or {}).get("persons", []) or []:
        for event in person.get("events", []) or []:
            if isinstance(event, dict):
                ensure_event_uid(event, source, str(person.get("id") or ""))
                count += 1
    return count

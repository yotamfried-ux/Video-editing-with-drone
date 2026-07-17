"""Expose parent person identity before raw primary-actor selection runs.

Gemini session JSON stores the canonical person ID on the parent person object.
Primary-actor filtering evaluates child events before the parsed-session enrichment
step, so crowded actions need that parent identity copied into each raw event first.
"""
from __future__ import annotations

import json
from typing import Any

from pipeline.primary_actor_policy import primary_actor_id

_INSTALLED_FLAG = "_sportreel_primary_actor_parent_identity_installed"


def install() -> None:
    """Patch raw selection so parent person IDs participate in centrality checks."""
    import pipeline.single_athlete_selection_policy as selection

    if getattr(selection, _INSTALLED_FLAG, False):
        return

    def rewrite_with_parent_identity(raw_text: str) -> str:
        data = selection._load_json(raw_text)
        for person in data.get("persons", []) or []:
            if not isinstance(person, dict):
                continue
            person_id = str(person.get("id") or "").strip()
            retained: list[dict[str, Any]] = []
            for raw_event in person.get("events", []) or []:
                if not isinstance(raw_event, dict):
                    continue
                event = dict(raw_event)
                if person_id and not primary_actor_id(event):
                    event["person_id"] = person_id
                allowed = selection._event_allowed(event)
                if allowed is not None:
                    retained.append(allowed)
            person["events"] = retained
        return json.dumps(data, ensure_ascii=False)

    # The analyzer parse wrapper resolves this module global at call time, so
    # replacing it here also updates the already-installed production wrapper.
    selection.rewrite_raw_selection_json = rewrite_with_parent_identity
    setattr(selection, _INSTALLED_FLAG, True)

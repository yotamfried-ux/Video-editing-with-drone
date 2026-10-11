#!/usr/bin/env python3
"""Isolated before/after regression for multi-person primary actor attribution.

This is a synthetic policy simulation, NOT a replay of the original 24 videos.
"""
import json
from pipeline.primary_actor_policy import classify_primary_actor

cases = [
    ("id_only_multi", {"athlete_id": "a"}, 2, None, True),
    ("continuity_only_multi", {"athlete_id": "a"}, 2, .8, True),
    ("explicit_unclear_multi", {"athlete_id": "a", "primary_actor_clear": False}, 2, .8, True),
    ("proven_multi", {"athlete_id": "a", "primary_actor_clear": True,
                      "identity_continuity": "stable", "primary_actor_confidence": .92}, 2, .8, False),
    ("single_visible", {"athlete_id": "a"}, 1, None, False),
    ("identity_switch", {"athlete_id": "a", "identity_switch": True}, 2, .9, True),
]

def previous_allowed(event, visible, continuity):
    # Prior production rule: absent explicit ambiguity, ID alone was enough.
    if event.get("identity_switch") or event.get("primary_actor_clear") is False:
        return False
    return bool(event.get("athlete_id")) or (continuity is not None and continuity >= .5) or visible <= 1

rows = []
for name, event, visible, continuity, must_block in cases:
    before = previous_allowed(event, visible, continuity)
    result = classify_primary_actor(event, visible_subject_count=visible,
                                    primary_continuity_ratio=continuity)
    after = result["decision"] != "review_required"
    assert after != must_block, (name, result)
    rows.append({"case": name, "before_allowed": before, "after_allowed": after,
                 "changed": before != after})
assert sum(row["changed"] for row in rows) == 2, rows
assert sum(row["before_allowed"] for row in rows) == 4, rows
assert sum(row["after_allowed"] for row in rows) == 2, rows
print(json.dumps({"scope": "synthetic primary actor policy only",
                  "before_allowed": 4, "after_allowed": 2,
                  "unsafe_multi_subject_allowed_before": 2,
                  "unsafe_multi_subject_allowed_after": 0,
                  "cases": rows}, indent=2))

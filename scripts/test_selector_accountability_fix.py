#!/usr/bin/env python3
"""Isolated selector decision-accountability before/after regression."""
import json
from pipeline.stages.selector_candidates import build_selector_candidate_events

persons = [{"id": "a", "events": [
    {"start": 10, "end": 18, "score": 9, "type": "ride", "description": "chosen"},
    {"start": 10, "end": 18, "score": 8, "type": "ride", "description": "dedup"},
    {"start": 10, "end": 18, "score": 4, "type": "ride", "description": "below threshold same timestamp"},
    {"start": 35, "end": 44, "score": 3, "type": "ride", "description": "below threshold"},
    {"start": 50, "end": 52, "score": 9, "type": "ride", "description": "short"},
]}]
payload = build_selector_candidate_events(persons, source_video="isolated.mp4")
rows = payload["candidates"]
assert len(rows) == 5, rows
assert payload["selected_count"] == 1, payload
assert payload["discarded_count"] == 4, payload
assert all(x["selected"] != x["discarded"] for x in rows), rows
assert len([x for x in rows if x["description"] == "below threshold same timestamp"]) == 1
assert next(x for x in rows if x["description"] == "below threshold same timestamp")["discard_cause"] == "score_below_selection_threshold"
print(json.dumps({"scope": "isolated selector decision ledger", "input_events": 5,
                  "before_accounted": 4, "after_accounted": len(rows),
                  "unexplained_before": 1, "unexplained_after": 0,
                  "selected": payload["selected_count"],
                  "discarded": payload["discarded_count"]}, indent=2))

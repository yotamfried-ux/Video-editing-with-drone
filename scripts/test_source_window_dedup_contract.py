#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT))
    from pipeline.source_window_dedup import dedupe_session, dedupe_source_window_events

    persons = [
        {
            "id": "person_A",
            "description": "pink board",
            "events": [
                {"type": "highlight", "score": 10, "start": 495.0, "end": 512.5, "description": "best overlapping event"},
            ],
        },
        {
            "id": "person_B",
            "description": "purple board",
            "events": [
                {"type": "wave_catch", "score": 8, "start": 493.0, "end": 517.0, "description": "lower priority duplicate"},
            ],
        },
        {
            "id": "person_C",
            "description": "separate surfer",
            "events": [
                {"type": "highlight", "score": 9, "start": 209.0, "end": 223.0, "description": "separate moment"},
            ],
        },
    ]

    deduped, dropped = dedupe_source_window_events(persons, default_source="source.mp4")
    counts = [len(person.get("events", [])) for person in deduped]
    require(counts == [1, 0, 1], f"unexpected event counts after dedup: {counts}")
    require(len(dropped) == 1, f"expected one dropped duplicate, got {len(dropped)}")
    require(dropped[0]["discard_cause"] == "source_window_overlap_lower_priority", "drop cause missing")
    require(dropped[0]["duplicate_of_source_window"]["start"] == 495.0, "duplicate reference missing")

    session = {"activity": "surfing", "persons": persons}
    result = dedupe_session(session, default_source="source.mp4")
    require(result["diagnostics"]["source_window_dedup_dropped_count"] == 1, "session diagnostics missing dropped count")
    require(len(result["persons"][1]["events"]) == 0, "duplicate event remained in session")
    require(session["persons"][1]["events"], "dedupe must not mutate original session")

    runtime = (ROOT / "pipeline/selector_candidate_runtime.py").read_text(encoding="utf-8")
    require("from pipeline.source_window_dedup import dedupe_session" in runtime, "runtime must import source window dedup")
    require("result = dedupe_session(result" in runtime, "runtime must dedupe analyzer result")

    print("source window dedup contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

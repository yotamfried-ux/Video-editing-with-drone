#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _event(src: str, score: int, fp: str | None) -> dict:
    ev = {
        "_src": src,
        "type": "snap",
        "start": 10.0,
        "end": 18.0,
        "score": score,
        "bbox_xyxy": [100, 100, 220, 260],
        "perception_frame_width": 640,
        "perception_frame_height": 480,
        "visible_ratio": 1.0,
        "perception_confidence": 0.9,
    }
    if fp:
        ev["event_fingerprint"] = fp
    return ev


def main() -> int:
    from pipeline.perception.event_fingerprint import deduplicate_cross_source_events, event_fingerprint

    low = _event("a.mp4", 7, "wave-42")
    high = _event("b.mp4", 9, "wave-42")
    out = deduplicate_cross_source_events([low, high])
    assert len(out) == 1
    assert out[0]["_src"] == "b.mp4"
    assert out[0]["dedup_duplicate_count"] == 2
    assert out[0]["dedup_dropped_duplicates"]

    out = deduplicate_cross_source_events([_event("a.mp4", 8, "wave-1"), _event("b.mp4", 8, "wave-2")])
    assert len(out) == 2

    weak = deduplicate_cross_source_events([
        {"_src": "a.mp4", "type": "snap", "start": 10, "end": 18, "score": 8},
        {"_src": "b.mp4", "type": "snap", "start": 10, "end": 18, "score": 8},
    ])
    assert len(weak) == 2

    s1 = _event("a.mp4", 8, None)
    s2 = _event("b.mp4", 8, None)
    s1["session_time_sec"] = 100.0
    s2["session_time_sec"] = 100.4
    assert event_fingerprint(s1) is not None
    assert len(deduplicate_cross_source_events([s1, s2])) == 1

    print("Cross-source dedup contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

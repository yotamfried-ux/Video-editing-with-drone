#!/usr/bin/env python3
"""Two clusters the model described differently are not merged on vaguer per-clip descriptions (0143 / 0152).

Run 43583126199 (main@7d6b544), identity_trace.json:
- model layer: cluster "Surfer in a white short-sleeve shirt on a pink longboard." (0143) and cluster
  "Surfer in a white long-sleeve shirt on a pink longboard." (0152), kept apart;
- per-clip descriptions: "surfer on a pink surfboard with a light-colored top and dark shorts" and
  "surfer in white shirt and black shorts on a pink surfboard", both parsed as an unnamed top;
- post-process merged the two clusters (structured score 1.0) and the catalog has two athletes.

1. The merge of these two clusters is refused; each keeps its own appearance.
2. Clusters whose descriptions do not conflict still merge (the fragment merge keeps working).
3. The other post-model merge of that run (a silhouette with a shirtless surfer) is not a description conflict.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def app(path: str, description: str, track: int) -> dict:
    return {"path": path, "_clip_index": path, "_person_id": "person_A", "description": description,
            "_description": description, "events": [{"start": 1.0, "end": 8.0, "track_id": track}]}


def main() -> int:
    from pipeline.stages.identity import _cluster_descriptions_conflict, _merge_compatible_structured_clusters

    short = "Surfer in a white short-sleeve shirt on a pink longboard."
    long_ = "Surfer in a white long-sleeve shirt on a pink longboard."
    clip_0143 = "surfer on a pink surfboard with a light-colored top and dark shorts"
    clip_0152 = "surfer in white shirt and black shorts on a pink surfboard"

    if not _cluster_descriptions_conflict(short, long_):
        raise SystemExit("short sleeves against long sleeves is a stated conflict between two clusters")

    merged = _merge_compatible_structured_clusters([
        {"description": short, "appearances": [app("DJI_0143_D.MP4", clip_0143, 10001)]},
        {"description": long_, "appearances": [app("DJI_0152_D.MP4", clip_0152, 10046)]},
    ])
    if len(merged) != 2 or any(len(c["appearances"]) != 1 for c in merged):
        raise SystemExit(f"0143 and 0152 are two athletes in the catalog and must stay two clusters, got {len(merged)}")

    same = "Surfer in a white shirt on a pink longboard."
    merged = _merge_compatible_structured_clusters([
        {"description": same, "appearances": [app("DJI_0143_D.MP4", clip_0143, 10001)]},
        {"description": same, "appearances": [app("DJI_0152_D.MP4", clip_0152, 10046)]},
    ])
    if len(merged) != 1:
        raise SystemExit("fragments of one athlete with agreeing descriptions must still merge")

    if _cluster_descriptions_conflict(
        "Silhouette of a surfer on a light blue surfboard.",
        "Shirtless surfer in dark shorts on a light blue longboard.",
    ):
        raise SystemExit("a silhouette names no clothing and conflicts with nothing")

    print("PASS: cluster description conflict keeps the model's split (0143 / 0152)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

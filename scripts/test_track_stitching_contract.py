#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def det(track_id: int, time_sec: float, bbox: list[float]) -> dict:
    return {
        "frame_index": int(time_sec * 24),
        "time_sec": time_sec,
        "bbox_xyxy": bbox,
        "frame_width": 1920,
        "frame_height": 1080,
        "confidence": 0.8,
        "class_id": 0,
        "class_name": "person",
        "track_id": track_id,
    }


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT))

    from pipeline.perception.track_stitching import stitch_detection_tracks, stitch_sidecar_payload, track_stitching_summary

    raw = [
        det(10, 10.0, [100, 100, 200, 300]),
        det(10, 11.0, [115, 105, 215, 305]),
        # Temporal + spatial continuation of track 10, should stitch to canonical 10.
        det(20, 12.5, [130, 110, 230, 310]),
        det(20, 13.0, [145, 115, 245, 315]),
        # Far away, should not stitch.
        det(30, 13.5, [900, 300, 1010, 520]),
        # Overlaps in time with canonical 10, should not stitch despite proximity.
        det(40, 10.5, [120, 110, 220, 310]),
    ]
    stitched = stitch_detection_tracks(raw, source_video="source.mp4")
    by_raw: dict[int, set[int]] = {}
    for item in stitched:
        by_raw.setdefault(int(item["raw_track_id"]), set()).add(int(item["track_id"]))

    require(by_raw[10] == {10}, f"track 10 should remain canonical 10: {by_raw}")
    require(by_raw[20] == {10}, f"track 20 should stitch into canonical 10: {by_raw}")
    require(by_raw[30] == {30}, f"far track 30 must stay separate: {by_raw}")
    require(by_raw[40] == {40}, f"time-overlapping track 40 must stay separate: {by_raw}")

    summary = track_stitching_summary(raw, stitched)
    require(summary["raw_track_count"] == 4, f"unexpected raw count: {summary}")
    require(summary["canonical_track_count"] == 3, f"unexpected canonical count: {summary}")
    require(summary["stitched_track_count"] == 1, f"unexpected stitched count: {summary}")
    require(all("raw_track_id" in item for item in stitched), "raw_track_id must be preserved on every stitched detection")

    payload = stitch_sidecar_payload({"source_video": "source.mp4", "status": "ok", "detections": raw})
    require(payload["track_stitching"]["canonical_track_count"] == 3, "sidecar payload must include stitching summary")
    require(any(item["raw_track_id"] != item["track_id"] for item in payload["detections"]), "sidecar detections must expose raw/canonical difference")

    generator = (ROOT / "scripts/generate_perception_sidecar.py").read_text(encoding="utf-8")
    producer = (ROOT / "pipeline/perception/producer.py").read_text(encoding="utf-8")
    for label, text in [("generator", generator), ("producer", producer)]:
        require("stitch_sidecar_payload" in text, f"{label} must stitch sidecar payloads")
    require("raw_track_id" in producer, "producer must preserve raw_track_id when normalizing stitched detections")

    print("track stitching contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

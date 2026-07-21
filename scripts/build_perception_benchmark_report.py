#!/usr/bin/env python3
"""Build a durable per-video tracker performance and fragmentation report."""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _track_key(item: dict[str, Any], field: str) -> str | None:
    value = item.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _duration_metrics(detections: list[dict[str, Any]], field: str) -> dict[str, Any]:
    times: dict[str, list[float]] = defaultdict(list)
    for item in detections:
        track_id = _track_key(item, field)
        timestamp = _number(item.get("time_sec"))
        if track_id is not None and timestamp is not None:
            times[track_id].append(timestamp)

    durations = [max(values) - min(values) for values in times.values() if values]
    gaps_over_one_second = 0
    for values in times.values():
        ordered = sorted(set(values))
        gaps_over_one_second += sum(1 for left, right in zip(ordered, ordered[1:]) if right - left > 1.0)

    return {
        "track_count": len(times),
        "median_duration_seconds": round(statistics.median(durations), 3) if durations else None,
        "tracks_under_two_seconds": sum(1 for duration in durations if duration < 2.0),
        "max_duration_seconds": round(max(durations), 3) if durations else None,
        "observed_gaps_over_one_second": gaps_over_one_second,
    }


def _sidecar_record(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    detections = [item for item in payload.get("detections", []) if isinstance(item, dict)]
    performance = payload.get("performance") if isinstance(payload.get("performance"), dict) else {}
    stitching = payload.get("track_stitching") if isinstance(payload.get("track_stitching"), dict) else {}
    raw_metrics = _duration_metrics(detections, "raw_track_id")
    canonical_metrics = _duration_metrics(detections, "track_id")

    return {
        "sidecar": path.name,
        "source_video": payload.get("source_video"),
        "status": payload.get("status"),
        "backend": payload.get("backend"),
        "model": payload.get("model"),
        "tracker": payload.get("tracker"),
        "with_reid": payload.get("with_reid"),
        "vid_stride": payload.get("vid_stride"),
        "imgsz": payload.get("imgsz"),
        "device": payload.get("device"),
        "detection_count": len(detections),
        "processed_frame_count": performance.get("processed_frame_count"),
        "wall_time_seconds": performance.get("wall_time_seconds"),
        "inference_frames_per_second": performance.get("inference_frames_per_second"),
        "effective_sampling_fps": performance.get("effective_sampling_fps"),
        "raw_track_count": stitching.get("raw_track_count", raw_metrics["track_count"]),
        "canonical_track_count": stitching.get("canonical_track_count", canonical_metrics["track_count"]),
        "stitched_track_count": stitching.get("stitched_track_count"),
        "raw_track_metrics": raw_metrics,
        "canonical_track_metrics": canonical_metrics,
        "requires_ground_truth_review": [
            "id_switch_count",
            "featured_athlete_identity_continuity",
            "visually_similar_athlete_false_merge",
        ],
    }


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_perception_benchmark_report.py SIDECar_DIR OUTPUT_JSON")
    sidecar_dir = Path(sys.argv[1])
    output = Path(sys.argv[2])
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted(sidecar_dir.glob("*.perception.json")) if sidecar_dir.exists() else []:
        try:
            records.append(_sidecar_record(path))
        except Exception as exc:  # Preserve diagnostics even when one sidecar is malformed.
            errors.append({"sidecar": path.name, "error": str(exc)})

    wall_times = [float(item["wall_time_seconds"]) for item in records if _number(item.get("wall_time_seconds")) is not None]
    report = {
        "schema_version": "sportreel.perception_benchmark.v1",
        "status": "ok" if records and not errors else "partial" if records else "no_sidecars",
        "video_count": len(records),
        "total_wall_time_seconds": round(sum(wall_times), 3),
        "videos": records,
        "errors": errors,
        "closure_note": (
            "Runtime and fragmentation are measured automatically. ID switches and identity correctness "
            "still require comparison with labeled or manually reviewed real footage."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Perception benchmark report: videos={len(records)} errors={len(errors)} wall_time={sum(wall_times):.3f}s")

    github_summary = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8") as handle:
            handle.write("## Perception benchmark\n\n")
            handle.write(f"- Videos measured: `{len(records)}`\n")
            handle.write(f"- Tracker wall time: `{sum(wall_times):.3f}s`\n")
            for item in records:
                handle.write(
                    f"- `{item['sidecar']}`: detections `{item['detection_count']}`, "
                    f"tracks `{item['raw_track_count']}→{item['canonical_track_count']}`, "
                    f"wall time `{item['wall_time_seconds']}`s\n"
                )
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render and probe a real 4K/30 silent SportReel fixture.

This test complements the pure policy tests by exercising FFmpeg through the
quality-first contain renderer and the final reel compiler. It deliberately uses
a short synthetic source while still satisfying the editor's real minimum-window
contract.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.quality_preserving_framing import (  # noqa: E402
    OUTPUT_FPS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    _render_clip,
    decide_framing,
    install,
    quality_output_issues,
)


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout[-2000:]}\n"
            f"stderr:\n{completed.stderr[-4000:]}"
        )
    return completed


def _probe(path: Path) -> dict:
    completed = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(completed.stdout)


def _rate(value: str) -> float:
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def _assert_media_contract(path: Path) -> None:
    report = _probe(path)
    streams = report.get("streams") or []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    assert len(video_streams) == 1, report
    assert not audio_streams, report

    video = video_streams[0]
    assert int(video.get("width") or 0) == OUTPUT_WIDTH, video
    assert int(video.get("height") or 0) == OUTPUT_HEIGHT, video
    assert video.get("codec_name") == "h264", video
    assert str(video.get("profile") or "").lower() == "high", video
    assert video.get("pix_fmt") == "yuv420p", video
    assert abs(_rate(video.get("avg_frame_rate") or "0/1") - OUTPUT_FPS) <= 0.05, video
    assert video.get("color_space") == "bt709", video
    assert video.get("color_primaries") == "bt709", video
    assert video.get("color_transfer") == "bt709", video

    issues = quality_output_issues(
        {
            "width": video["width"],
            "height": video["height"],
            "fps": _rate(video["avg_frame_rate"]),
        },
        [],
    )
    assert issues == [], issues


def main() -> int:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise AssertionError("ffmpeg and ffprobe are required")

    with tempfile.TemporaryDirectory(prefix="sportreel-4k-contract-") as temp_dir:
        root = Path(temp_dir)
        os.environ["TMP_DIR"] = str(root)
        source = root / "source-4k30.mp4"
        final = root / "final-part.mp4"

        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=3840x2160:rate=30:duration=3.20",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-movflags",
                "+faststart",
                str(source),
            ],
            timeout=300,
        )

        event = {
            "event_id": "fixture-readable-surf-ride",
            "type": "surf_ride",
            "start": 0.10,
            "end": 1.00,
            "perception_evidence_status": "tracker_sidecar",
            "track_id": 7,
            "bbox_xyxy": [1200, 500, 2640, 1900],
            "perception_frame_width": 3840,
            "perception_frame_height": 2160,
            "perception_confidence": 0.95,
            "visible_ratio": 1.0,
            "visible_track_ids": [7, 11],
        }
        decision = decide_framing(event, sport="surfing")
        assert decision.mode == "contain", decision

        clip_path = _render_clip(str(source), event, 1, decision)
        assert clip_path, "contain renderer did not produce a clip"
        clip = Path(clip_path)
        _assert_media_contract(clip)

        install()
        from pipeline.stages import editor

        compiled = editor.compile_reel(
            [str(clip)],
            logo_path="",
            output_path=str(final),
            sport="surfing",
            athlete_label="fixture athlete",
            music_path=None,
            transitions=None,
            style={"pace": "moderate"},
            fps=30,
        )
        assert compiled == str(final), compiled
        assert final.exists(), final
        _assert_media_contract(final)

        print(json.dumps({
            "status": "pass",
            "source": source.name,
            "clip": clip.name,
            "final": final.name,
            "width": OUTPUT_WIDTH,
            "height": OUTPUT_HEIGHT,
            "fps": OUTPUT_FPS,
            "audio_streams": 0,
            "framing_mode": decision.mode,
        }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

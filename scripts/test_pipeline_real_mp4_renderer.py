#!/usr/bin/env python3
"""Actual SportReel editor MP4 smoke: real cut_clip -> encoded H264 -> visual oracle.

No provider/network/production calls. Synthetic color-labelled subjects are an
explicit ground truth; this does NOT qualify perception, tracking, or LLM QA.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=240)


def probe(path: Path) -> dict:
    data = json.loads(run("ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=codec_name,width,height,nb_frames",
                          "-of", "json", str(path)).stdout)
    return data["streams"][0]


def pixel_at(path: Path, x: int, y: int) -> tuple[int, int, int]:
    # Read ONE frame pixel using FFmpeg, independent of the editor.
    rgb = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "2", "-i", str(path),
         "-vf", f"crop=2:2:{x}:{y},format=rgb24", "-frames:v", "1",
         "-f", "rawvideo", "-"],
        capture_output=True, timeout=60, check=True,
    ).stdout
    assert len(rgb) == 12, f"missing decoded pixels: {len(rgb)}"
    return tuple(rgb[:3])


def main() -> None:
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required"
    with tempfile.TemporaryDirectory(prefix="sportreel-real-mp4-") as d:
        folder = Path(d)
        cfg = types.SimpleNamespace(
            TMP_DIR=str(folder), QUALITY_LOG_FILE=str(folder / "quality.jsonl"),
            MIN_SOURCE_HEIGHT=1440, SLOWMO_INTERPOLATE=False,
        )
        sys.modules["config"] = cfg
        from pipeline.stages import editor
        # Keep actual production cut_clip function, crop/grade/filter and encoder.
        # Synthetic fixture has a green subject in left third and red in right.
        source = folder / "two_subjects.mp4"
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:r=30:d=6",
            "-vf", "drawbox=x=140:y=300:w=450:h=450:color=green:t=fill,"
                   "drawbox=x=1330:y=300:w=450:h=450:color=red:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(source))
        info = {"width": 1920, "height": 1080, "fps": 30.0,
                "zoom_headroom": 1.0, "can_slowmo": False}
        outputs = {}
        for label, cx in (("left", 0.20), ("right", 0.80)):
            event = {"start": 0, "end": 4, "type": "highlight", "score": 6,
                     "crop_x": cx, "crop_y": 0.5, "edit": {"zoom": 1.0, "slowmo": False}}
            result = editor.cut_clip(str(source), event, 0 if label == "left" else 1,
                                     sport="surfing", source_info=info, target_fps=30)
            assert result and Path(result).is_file(), f"editor failed to render {label}"
            video = Path(result)
            spec = probe(video)
            assert spec["codec_name"] == "h264" and (spec["width"], spec["height"]) == (1080, 1920), spec
            outputs[label] = {"path": video.name, "spec": spec,
                              "pixel": pixel_at(video, 540, 960)}
        # The left crop must show a predominantly green subject; the right a red one.
        # Real FFmpeg encode/decode colors may shift slightly, compare channels.
        left = outputs["left"]["pixel"]
        right = outputs["right"]["pixel"]
        assert left[1] > left[0] * 1.25 and left[1] > left[2] * 1.25, outputs
        assert right[0] > right[1] * 1.25 and right[0] > right[2] * 1.25, outputs
        print(json.dumps({"result": "PASS", "engine": "pipeline.stages.editor.cut_clip",
                          "real_encoded_mp4": True, "checks": outputs}, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Actual SportReel editor MP4 smoke: real cut_clip -> encoded H264 -> visual oracle.

No provider/network/production calls. Synthetic color-labelled subjects are an
explicit ground truth; this does NOT qualify perception, tracking, or LLM QA.
"""
from __future__ import annotations
import hashlib
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




def persist_synthetic_evidence(
    suite: str, folder: Path, source: Path,
    rendered: dict[str, Path], checks: dict,
) -> None:
    """Opt-in export of strictly synthetic evidence before temp cleanup."""
    requested = os.environ.get("SPORTREEL_CI_VIDEO_EVIDENCE_DIR")
    if not requested:
        return
    runner = os.environ.get("RUNNER_TEMP")
    assert runner, "evidence export requires RUNNER_TEMP"
    runner_dir = Path(runner).resolve(strict=True)
    evidence_dir = runner_dir / "sportreel-video-evidence"
    dest_root = Path(requested)
    assert dest_root.is_absolute() and dest_root == evidence_dir, "unapproved evidence path"
    assert not dest_root.is_symlink(), "symlink evidence root forbidden"
    assert suite in ("renderer", "track-to-render"), "unapproved evidence suite"
    assert set(rendered) == {"left", "right"}, "unexpected rendered subjects"
    assert set(checks) == {"left", "right"}, "unexpected QA subjects"
    dest = dest_root / suite
    assert not dest.exists() and not dest.is_symlink(), "evidence folder already exists"
    dest.mkdir(parents=True, exist_ok=False)
    assert dest.resolve() == dest, "evidence folder escaped runner temp"

    allowed_sources = {"source.mp4": source,
                       "left.mp4": rendered["left"],
                       "right.mp4": rendered["right"]}
    files = {}
    for name, original in allowed_sources.items():
        src = Path(original)
        assert src.is_file() and not src.is_symlink(), "missing or symlink source MP4"
        assert src.resolve().is_relative_to(folder.resolve()), "source escaped test fixture"
        output = dest / name
        assert not output.exists() and not output.is_symlink(), "output already exists"
        shutil.copyfile(src, output)
        assert 0 < output.stat().st_size < 200_000_000, "invalid synthetic MP4 size"
        spec = probe(output)
        assert spec["codec_name"] == "h264", "non-H264 video in evidence"
        files[name] = {
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size,
            "codec": spec["codec_name"],
            "width": spec["width"],
            "height": spec["height"],
            "frames": int(spec["nb_frames"]),
        }
        expected_size = (1920, 1080) if name == "source.mp4" else (1080, 1920)
        assert (spec["width"], spec["height"]) == expected_size, "incorrect evidence dimensions"
        assert files[name]["frames"] > 0, "zero-frame evidence video"
    def sample(label: str) -> list[int]:
        item = checks[label]
        rgb = item["pixel"] if suite == "renderer" else item["decoded_rgb"]
        assert len(rgb) == 3 and all(0 <= int(c) <= 255 for c in rgb)
        return [int(c) for c in rgb]
    left, right = sample("left"), sample("right")
    assert left[1] > left[0] * 1.25 and left[1] > left[2] * 1.25
    assert right[0] > right[1] * 1.25 and right[0] > right[2] * 1.25
    report = {
        "schema": "sportreel.synthetic-video-evidence.v1",
        "suite": suite,
        "result": "PASS",
        "synthetic_fixture_only": True,
        "real_detector_executed": False,
        "visual_oracle_executed": True,
        "github_checkout_sha": os.getenv("GITHUB_SHA", ""),
        "left_center_pixel_rgb": left,
        "right_center_pixel_rgb": right,
        "files": files,
    }
    if suite == "track-to-render":
        report["canonical_track_ids"] = {
            "left": str(checks["left"]["canonical_track_id"]),
            "right": str(checks["right"]["canonical_track_id"]),
        }
        assert report["canonical_track_ids"] == {"left": "10", "right": "30"}
    (dest / "qualification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

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
        rendered_paths = {}
        for label, cx in (("left", 0.20), ("right", 0.80)):
            event = {"start": 0, "end": 4, "type": "highlight", "score": 6,
                     "crop_x": cx, "crop_y": 0.5, "edit": {"zoom": 1.0, "slowmo": False}}
            result = editor.cut_clip(str(source), event, 0 if label == "left" else 1,
                                     sport="surfing", source_info=info, target_fps=30)
            assert result and Path(result).is_file(), f"editor failed to render {label}"
            video = Path(result)
            rendered_paths[label] = video
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
        persist_synthetic_evidence("renderer", folder, source, rendered_paths, outputs)
        print(json.dumps({"result": "PASS", "engine": "pipeline.stages.editor.cut_clip",
                          "real_encoded_mp4": True, "checks": outputs}, indent=2))


if __name__ == "__main__":
    main()

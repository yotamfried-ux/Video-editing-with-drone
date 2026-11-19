#!/usr/bin/env python3
"""Evaluator-side rendered-reel inspection (never part of the inference path).

Follows Engineering-OS capability-registry/video-analysis/mcp-video-analyzer.md: deterministic evidence first
(metadata, decode errors, black/frozen frames, cuts), then timestamped frames for the agent / reviewer to look at.
Uses FFmpeg/FFprobe only, so it runs on any CI runner; `npx mcp-video-analyzer` can be pointed at the same files.

  inspect_reel.py REEL.mp4 [--out DIR] [--sheet-fps 1] [--burst] [--compare OTHER.mp4]

Writes DIR/<stem>.inspection.json and, unless --no-frames, DIR/<stem>.sheet.jpg (frames with reel time burnt in)
and DIR/<stem>.burst_<n>.jpg (10 fps, +-0.5 s around each detected cut). A non-empty `defects` list means the
reel fails the deterministic output contract; looking at the sheet is still required before any media verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

EXPECTED = {"codec": "h264", "aspect": 9 / 16, "fps": 30.0}


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames:format=duration",
                "-of", "json", str(path)])
    data = json.loads(out.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = str(video.get("r_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {"codec": video.get("codec_name"), "width": video.get("width"), "height": video.get("height"), "fps": round(fps, 3),
            "duration": float((data.get("format") or {}).get("duration") or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def scan(path: Path, scene: float = 0.35) -> dict:
    """One decode pass: decode errors, black and frozen intervals, scene cuts."""
    out = _run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-an", "-vf",
                f"scale=480:-2,blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.003:d=0.5,"
                f"select='gt(scene,{scene})',showinfo", "-f", "null", "-"])
    log = out.stderr
    cuts = [round(float(t), 3) for t in re.findall(r"pts_time:([0-9.]+)", log)]
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", log)]
    freezes = re.findall(r"freeze_start: ([0-9.]+)", log)
    freeze_d = [float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", log)]
    errors = [l for l in log.splitlines() if re.search(r"error|corrupt|invalid", l, re.I) and "Error opening" not in l]
    return {"cuts": cuts, "black": black, "freezes": [(float(s), d) for s, d in zip(freezes, freeze_d)],
            "decode_error_lines": len(errors)}


def frames(path: Path, out: Path, stem: str, info: dict, cuts: list[float], sheet_fps: float, burst: bool) -> list[str]:
    made = []
    cols = max(6, min(16, int(info["duration"] * sheet_fps / 3) or 6))
    sheet = out / f"{stem}.sheet.jpg"
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
          f"fps={sheet_fps},scale=180:-2,drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=14:fontcolor=yellow:box=1:"
          f"boxcolor=black@0.6,tile={cols}x{max(1, int(info['duration'] * sheet_fps / cols) + 1)}",
          "-frames:v", "1", str(sheet)])
    if sheet.exists():
        made.append(str(sheet))
    for i, t in enumerate(cuts[:12] if burst else []):
        target = out / f"{stem}.burst_{i}.jpg"
        _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t - 0.5):.3f}", "-t", "1.0", "-i", str(path), "-vf",
              "fps=10,scale=200:-2,drawtext=text='%{pts\\:hms}':x=4:y=4:fontsize=13:fontcolor=yellow:box=1:"
              "boxcolor=black@0.6,tile=10x1", "-frames:v", "1", str(target)])
        if target.exists():
            made.append(str(target))
    return made


def defects(info: dict, s: dict) -> list[str]:
    out = []
    if info["codec"] != EXPECTED["codec"]:
        out.append(f"codec {info['codec']} != h264")
    if info["width"] and info["height"] and abs(info["width"] / info["height"] - EXPECTED["aspect"]) > 0.01:
        out.append(f"aspect {info['width']}x{info['height']} is not 9:16")
    if abs(info["fps"] - EXPECTED["fps"]) > 0.05:
        out.append(f"fps {info['fps']} != 30")
    if info["duration"] <= 0:
        out.append("empty or unreadable duration")
    if s["decode_error_lines"]:
        out.append(f"{s['decode_error_lines']} decode error lines")
    out += [f"black {a:.2f}-{b:.2f}s" for a, b in s["black"] if not (b >= info["duration"] - 0.6)]   # end fade allowed
    out += [f"frozen {t:.2f}s for {d:.2f}s" for t, d in s["freezes"]]
    return out


def inspect(path: Path, out: Path, sheet_fps: float = 1.0, burst: bool = False, with_frames: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    info = probe(path)
    s = scan(path)
    report = {"schema": "sportreel.reel_inspection.v1", "file": path.name, "sha256": sha256(path), **info,
              "cuts": s["cuts"], "black": s["black"], "freezes": s["freezes"],
              "decode_error_lines": s["decode_error_lines"], "defects": defects(info, s)}
    report["frames"] = frames(path, out, path.stem, info, s["cuts"], sheet_fps, burst) if with_frames else []
    (out / f"{path.stem}.inspection.json").write_text(json.dumps(report, indent=1))
    return report


def compare(a: dict, b: dict) -> dict:
    """Before/after: duration, cut count and positions, defects."""
    return {"a": a["file"], "b": b["file"], "same_bytes": a["sha256"] == b["sha256"],
            "duration_delta_s": round(b["duration"] - a["duration"], 3), "cuts_a": a["cuts"], "cuts_b": b["cuts"],
            "defects_a": a["defects"], "defects_b": b["defects"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reel", type=Path)
    ap.add_argument("--out", type=Path, default=Path("reel-inspection"))
    ap.add_argument("--sheet-fps", type=float, default=1.0)
    ap.add_argument("--burst", action="store_true")
    ap.add_argument("--no-frames", action="store_true")
    ap.add_argument("--compare", type=Path)
    a = ap.parse_args()
    rep = inspect(a.reel, a.out, a.sheet_fps, a.burst, not a.no_frames)
    if a.compare:
        rep2 = inspect(a.compare, a.out, a.sheet_fps, a.burst, not a.no_frames)
        print(json.dumps(compare(rep, rep2), indent=1))
    print(json.dumps({k: rep[k] for k in ("file", "sha256", "duration", "cuts", "defects")}, indent=1))
    return 1 if rep["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

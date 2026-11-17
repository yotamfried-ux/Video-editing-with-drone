#!/usr/bin/env python3
"""Technical + visual-evidence check of rendered reel MP4s (decoded media, not the EDL).

For every MP4 in a directory:
  * SHA-256, size, ffprobe stream facts (codec, resolution, fps, duration, frame count)
  * full decode with error detection (`ffmpeg -v error -f null`): any decoder error is reported
  * frozen stretches (freezedetect, >= 0.5 s) and black stretches (blackdetect, >= 0.3 s)
  * contact sheets of the DECODED reel at 2 fps (4 x 5 tiles), with the reel time burnt in, for visual QA

usage: reel_media_check.py REELS_DIR OUT_DIR   ->  OUT_DIR/media_check.json + OUT_DIR/<reel>/sheet_XX.jpg
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
             "stream=codec_name,width,height,r_frame_rate,nb_read_frames:format=duration", "-of", "json", str(path)])
    d = json.loads(r.stdout or "{}")
    s = (d.get("streams") or [{}])[0]
    num, _, den = str(s.get("r_frame_rate", "0/1")).partition("/")
    return {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
            "fps": round(float(num) / float(den or 1), 3) if num else None,
            "frames": int(s.get("nb_read_frames") or 0), "duration_sec": round(float(d.get("format", {}).get("duration") or 0), 3)}


def detect(path: Path) -> dict:
    r = run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", "freezedetect=n=0.003:d=0.5,blackdetect=d=0.3:pix_th=0.10",
             "-an", "-f", "null", "-"])
    log = r.stderr
    freezes = re.findall(r"freeze_duration: ([0-9.]+)", log)
    blacks = re.findall(r"black_duration:([0-9.]+)", log)
    errors = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"]).stderr.strip().splitlines()
    return {"decode_errors": errors[:10], "decode_error_count": len(errors),
            "frozen_stretches_sec": [round(float(x), 2) for x in freezes],
            "black_stretches_sec": [round(float(x), 2) for x in blacks]}


def sheets(path: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
         "fps=2,scale=270:-2,drawtext=text='%{pts\\:hms}':x=6:y=6:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6",
         str(frames / "f%04d.jpg")])
    files = sorted(frames.glob("f*.jpg"))
    n = 0
    for i in range(0, len(files), 20):
        chunk = files[i:i + 20]
        run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "sequence", "-start_number", str(i + 1), "-i",
             str(frames / "f%04d.jpg"), "-frames:v", "1", "-vf", f"tile=5x4:nb_frames={len(chunk)}",
             str(out / f"sheet_{i // 20:02d}.jpg")])
        n += 1
    return n


def main() -> int:
    reels, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for mp4 in sorted(reels.glob("*.mp4")):
        row = {"file": mp4.name, "bytes": mp4.stat().st_size, "sha256": hashlib.sha256(mp4.read_bytes()).hexdigest()}
        row.update(probe(mp4))
        row.update(detect(mp4))
        row["sheets"] = sheets(mp4, out / mp4.stem)
        row["technical_ok"] = (row["decode_error_count"] == 0 and row["frames"] > 0
                               and not any(f >= 1.0 for f in row["frozen_stretches_sec"]))
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("file", "duration_sec", "fps", "width", "height", "decode_error_count",
                                              "frozen_stretches_sec", "technical_ok")}))
    (out / "media_check.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

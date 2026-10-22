#!/usr/bin/env python3
"""Read-only: build timestamped contact sheets for the review drafts and their RAW/PROCESSED sources.

The draft MP4s and the original footage live in R2, which automation outside CI cannot reach. This
runs in CI, streams frames out of R2 (presigned URL, no full download for sources), and writes small
JPEG contact sheets plus a manifest.json so a reviewer can compare each final reel to its original.
It never writes, moves or deletes anything in R2.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations import r2_storage  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv")


def _probe(src: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,codec_name:format=duration,size", "-of", "json", src],
        capture_output=True, text=True, timeout=120,
    )
    try:
        data = json.loads(out.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        return {
            "width": stream.get("width"), "height": stream.get("height"),
            "fps": stream.get("r_frame_rate"), "codec": stream.get("codec_name"),
            "duration_s": float(fmt["duration"]) if fmt.get("duration") else None,
            "size_bytes": int(fmt["size"]) if fmt.get("size") else None,
        }
    except Exception as exc:  # best effort
        return {"probe_error": str(exc)}


def _sheets(src: str, out_dir: Path, stem: str, info: dict, step_s: float, cap_s: float) -> list[str]:
    w, h = info.get("width") or 16, info.get("height") or 9
    portrait = h > w
    tile_w, cols, rows = (180, 8, 2) if portrait else (320, 4, 5)
    vf = (
        f"fps=1/{step_s},scale={tile_w}:-2,"
        f"drawtext=fontfile={FONT}:text='%{{pts\\:flt}}s':x=4:y=4:fontsize=18:fontcolor=yellow:"
        f"box=1:boxcolor=black@0.6,tile={cols}x{rows}:padding=2:margin=2"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{stem}_%02d.jpg")
    cmd = ["ffmpeg", "-v", "error", "-y", "-t", str(cap_s), "-i", src, "-an", "-vf", vf,
           "-q:v", "5", pattern]
    subprocess.run(cmd, check=True, timeout=1800)
    return sorted(p.name for p in out_dir.glob(f"{stem}_*.jpg"))


def main() -> int:
    req = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_root = Path(sys.argv[2])
    draft_step = 1.0 / float(req.get("draft_fps", 2))
    src_step = float(req.get("source_step_sec", 2))
    src_cap = float(req.get("source_cap_sec", 60))
    src_filter = req.get("sources") or "all"

    client = r2_storage._client()
    bucket = r2_storage._bucket()

    def presign(key: str) -> str:
        return client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)

    manifest: dict = {"drafts": [], "sources": []}

    if req.get("include_drafts", True):
        for obj in sorted(r2_storage.list_objects(r2_storage.REVIEW_PREFIX), key=lambda o: o["Key"]):
            key = obj["Key"]
            if not key.lower().endswith(VIDEO_EXTS):
                continue
            name = Path(key).name
            stem = "draft_%02d" % (len(manifest["drafts"]) + 1)
            try:
                url = presign(key)
                info = _probe(url)
                sheets = _sheets(url, out_root / "drafts", stem, info, draft_step, 120)
                manifest["drafts"].append({"id": stem, "key": key, "name": name, "info": info, "sheets": sheets})
                print(f"draft {stem} {name} {info.get('duration_s')}s sheets={len(sheets)}", flush=True)
            except Exception as exc:
                manifest["drafts"].append({"id": stem, "key": key, "name": name, "error": str(exc)})
                print(f"draft FAILED {name}: {exc}", flush=True)

    keys: list[str] = []
    for prefix in (r2_storage.PROCESSED_PREFIX, r2_storage.RAW_PREFIX):
        keys += [o["Key"] for o in r2_storage.list_objects(prefix) if o["Key"].lower().endswith(VIDEO_EXTS)]
    for key in sorted(keys):
        name = Path(key).name
        if src_filter != "all" and not any(token in name for token in src_filter):
            continue
        stem = "src_" + Path(name).stem
        try:
            url = presign(key)
            info = _probe(url)
            sheets = _sheets(url, out_root / "sources", stem, info, src_step, src_cap)
            manifest["sources"].append({"key": key, "name": name, "info": info, "sheets": sheets})
            print(f"source {name} {info.get('duration_s')}s sheets={len(sheets)}", flush=True)
        except Exception as exc:
            manifest["sources"].append({"key": key, "name": name, "error": str(exc)})
            print(f"source FAILED {name}: {exc}", flush=True)

    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"drafts={len(manifest['drafts'])} sources={len(manifest['sources'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

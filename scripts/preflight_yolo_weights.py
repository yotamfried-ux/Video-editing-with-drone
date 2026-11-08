#!/usr/bin/env python3
"""Prewarm exact YOLO weights before launching parallel video workers.

The GitHub release endpoint returned HTTP 504 in production and real-video CI.
Use pinned official Ultralytics Hugging Face weights, verify their SHA256 and
publish atomically so concurrent worker subprocesses never download the model.
This performs no inference and does not touch raw or Ground Truth media.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

_REVISION = "c1ac518816e34361864c80db5bdfc4fa58e68baa"
_ASSETS = {
    "yolo11n.pt": "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1",
    "yolo11s.pt": "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5",
}


def effective_model(command: str, default: str) -> str:
    """Use actual producer CLI override; the workflow env default can differ."""
    parts = shlex.split(command or "")
    for idx, part in enumerate(parts):
        if part == "--ultralytics-model" and idx + 1 < len(parts):
            return parts[idx + 1]
        if part.startswith("--ultralytics-model="):
            return part.partition("=")[2]
    return (default or "yolo11s.pt").strip() or "yolo11s.pt"


def is_verified(path: Path, sha256: str) -> bool:
    if not path.is_file() or path.stat().st_size < 100_000:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == sha256


def ensure_official_weight(model: str, output_dir: Path = Path(".")) -> Path:
    """Fail closed on checksum/network errors; never adopt a truncated .pt."""
    target = output_dir / model
    expected = _ASSETS.get(model)
    if expected is None:
        if not target.is_file():
            raise ValueError(f"No verified mirror for custom YOLO model: {model}")
        return target
    if is_verified(target, expected):
        print(f"YOLO asset ready and SHA256 verified: {model} (cached)", flush=True)
        return target
    url = f"https://huggingface.co/Ultralytics/YOLO11/resolve/{_REVISION}/{model}"
    last_error: Exception | None = None
    for attempt in range(1, 4):
        fd, name = tempfile.mkstemp(prefix=".yolo-asset-", suffix=".pt", dir=output_dir)
        try:
            with os.fdopen(fd, "wb") as sink:
                request = Request(url, headers={"User-Agent": "SportReel-YOLO-Preflight/1.0"})
                with urlopen(request, timeout=45) as source:
                    while chunk := source.read(1024 * 1024):
                        sink.write(chunk)
            temporary = Path(name)
            if not is_verified(temporary, expected):
                raise ValueError(f"Model checksum mismatch or partial download: {model}")
            os.replace(temporary, target)
            print(f"YOLO asset ready and SHA256 verified: {model} (downloaded)", flush=True)
            return target
        except (OSError, ValueError) as exc:
            last_error = exc
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass
            print(f"YOLO asset download attempt {attempt}/3 failed: {type(exc).__name__}", flush=True)
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(f"Cannot preflight verified YOLO weights for {model}") from last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    model = args.model or effective_model(
        os.getenv("SPORTREEL_PERCEPTION_COMMAND", ""),
        os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "yolo11s.pt"),
    )
    path = ensure_official_weight(model)
    from ultralytics import YOLO
    YOLO(str(path))
    print(f"YOLO model load passed: {model}", flush=True)


if __name__ == "__main__":
    main()

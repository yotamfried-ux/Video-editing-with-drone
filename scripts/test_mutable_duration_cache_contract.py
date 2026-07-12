#!/usr/bin/env python3
"""Prove that a QA retry rewriting the same clip path gets a fresh duration."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import integrations.ffmpeg as ffmpeg


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    ffmpeg.clear_duration_cache()
    calls: list[str] = []

    def fake_ffprobe(cmd, text=True, timeout=30):
        del text, timeout
        path = str(cmd[-1])
        calls.append(path)
        return Path(path).read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(ffmpeg.subprocess, "check_output", side_effect=fake_ffprobe):
        clip = Path(tmpdir) / "source_clip02.mp4"
        clip.write_text("11.0", encoding="utf-8")
        first = ffmpeg.get_duration(str(clip))
        second = ffmpeg.get_duration(str(clip))
        require(first == 11.0 and second == 11.0, "stable clip duration is wrong")
        require(len(calls) == 1, "unchanged file should still benefit from caching")

        # Reproduce run 29194242123: QA renders a longer replacement to the same
        # path. Force a distinct nanosecond revision even on coarse filesystems.
        clip.write_text("25.5", encoding="utf-8")
        stat = clip.stat()
        os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        repaired = ffmpeg.get_duration(str(clip))
        require(repaired == 25.5, "rewritten QA clip reused stale 11-second duration")
        require(len(calls) == 2, "file revision did not invalidate the duration cache")

        # Same path and same byte size must also invalidate when mtime/ctime changes.
        clip.write_text("19.5", encoding="utf-8")
        stat = clip.stat()
        os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        require(ffmpeg.get_duration(str(clip)) == 19.5, "same-size replacement remained stale")
        require(len(calls) == 3, "same-size rewrite did not produce a new cache revision")

    print("mutable duration cache contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

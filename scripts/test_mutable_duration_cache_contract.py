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
    durations = iter(["11.0", "25.5", "19.5"])
    revisions = iter([
        (10, 100, 100, 4),
        (10, 100, 100, 4),  # unchanged file: same cache key
        (10, 200, 200, 4),  # in-place longer replacement at the same path
        (11, 200, 200, 4),  # atomic same-size replacement: inode alone changes
    ])

    def fake_ffprobe(cmd, text=True, timeout=30):
        del text, timeout
        calls.append(str(cmd[-1]))
        return next(durations)

    with patch.object(ffmpeg, "_file_revision", side_effect=lambda _path: next(revisions)), patch.object(
        ffmpeg.subprocess, "check_output", side_effect=fake_ffprobe
    ):
        path = "/tmp/source_clip02.mp4"
        require(ffmpeg.get_duration(path) == 11.0, "initial clip duration is wrong")
        require(ffmpeg.get_duration(path) == 11.0, "stable cache lookup changed the duration")
        require(len(calls) == 1, "unchanged revision should use the cache")

        require(ffmpeg.get_duration(path) == 25.5, "rewritten QA clip reused stale 11-second duration")
        require(len(calls) == 2, "new timestamp revision did not force a fresh ffprobe")

        require(ffmpeg.get_duration(path) == 19.5, "same-size atomic replacement remained stale")
        require(len(calls) == 3, "new inode did not force a fresh ffprobe")

    with tempfile.TemporaryDirectory() as tmpdir:
        clip = Path(tmpdir) / "source_clip02.mp4"
        replacement = Path(tmpdir) / "replacement.mp4"
        clip.write_text("11.0", encoding="utf-8")
        before = ffmpeg._file_revision(str(clip))
        replacement.write_text("25.5", encoding="utf-8")
        os.replace(replacement, clip)
        after = ffmpeg._file_revision(str(clip))
        require(before != after, "atomic same-path replacement did not change the cache revision")
        require(before[0] != after[0], "atomic replacement did not change inode evidence")

    require(callable(getattr(ffmpeg.get_duration, "cache_clear", None)), "cache_clear compatibility surface missing")
    print("mutable duration cache contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

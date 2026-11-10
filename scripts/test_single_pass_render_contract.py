#!/usr/bin/env python3
"""Contract: each reel is rendered in ONE ffmpeg pass (one lossy encode), never at the cost of the reel.

Before: every clip was a lossy 4K x264 encode (CRF 12, 45 Mb/s cap) that compile_reel decoded and encoded
again (CRF 14). Measured on a 3-clip 4K vertical reel: 112 s -> 68 s with equal-or-better quality
(SSIM vs a lossless render 0.833 -> 0.840) at a third of the size. Pinned here with real ffmpeg:

1. clips are deferred render specs (no per-clip encode, no clip file) with exact frame-based durations;
2. compile renders the whole reel in exactly one ffmpeg run, frame count matching the timeline;
3. the deferred-clip registry is emptied after compile;
4. if the single pass fails, the clips are encoded the old way and the reel is still produced;
5. per-clip QA (QA_CROP_CHECK) and SPORTREEL_SINGLE_PASS_RENDER=0 keep the per-clip path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"single-pass render contract FAILED: {msg}")


def frames(path: str) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return int(out)


def main() -> None:
    if shutil.which("ffmpeg") is None:
        fail("ffmpeg is required (the production pipeline always has it)")
    with tempfile.TemporaryDirectory(prefix="sportreel-single-pass-") as tmp:
        os.environ["TMP_DIR"] = tmp
        os.environ.pop("SPORTREEL_SINGLE_PASS_RENDER", None)
        src = os.path.join(tmp, "DJI_src_0001_D.MP4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=14",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p", src], check=True)

        import pipeline.quality_preserving_framing as q

        q.install()
        import pipeline.stages.editor as editor

        runs: list[list[str]] = []
        real_run = subprocess.run

        def spy(cmd, *args, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "ffmpeg":
                runs.append(cmd)
            return real_run(cmd, *args, **kwargs)

        q.subprocess.run = spy
        editor.subprocess.run = spy

        D = q.FramingDecision
        kf = ((0.5, 100.0, 0.0), (4.6, 500.0, 0.0))
        jobs = [
            ({"start": 0.5, "end": 4.6}, D("follow_crop", "t", 1.0, .5, .5, .9, 1, .2, .01, 1, path=kf, frame_width=1920, frame_height=1080)),
            ({"start": 4.6, "end": 9.0}, D("contain", "t", 1.0, .5, .5, .9, 1, .2, .01, 1)),
            ({"start": 9.0, "end": 13.2, "frame_width": 1920, "frame_height": 1080}, D("track_crop", "t", 1.2, .4, .6, .9, 1, .2, .01, 1)),
        ]

        # 1. deferred clips
        clips = [q._render_clip(src, ev, 400 + i, dec, defer=q.single_pass_enabled()) for i, (ev, dec) in enumerate(jobs)]
        if runs:
            fail(f"single pass must not encode clips individually, saw {len(runs)} ffmpeg run(s)")
        if any(os.path.exists(c) for c in clips):
            fail("deferred clips must not exist as files")
        windows = [editor._clamp(ev["start"], ev["end"], src) for ev, _ in jobs]
        expected = [round((end - start) * q.OUTPUT_FPS) for start, end in windows]
        if expected != [123, 132, 126]:
            fail(f"test windows unexpectedly clamped: {windows}")
        got = [round(editor._get_duration(c) * q.OUTPUT_FPS) for c in clips]
        if got != expected:
            fail(f"virtual clip durations must be exact frame counts {expected}, got {got}")

        # 2. one pass
        out = os.path.join(tmp, "reel_single.mp4")
        transitions = ["slide", "cut", "cut"]
        reel = editor.compile_reel(clips, "", out, sport="surfing", transitions=transitions, fps=30)
        if not reel or not os.path.exists(reel):
            fail("single-pass compile produced no reel")
        if len(runs) != 1:
            fail(f"the reel must be rendered in exactly one ffmpeg run, saw {len(runs)}")
        if "-maxrate" not in runs[0] or runs[0].count("-i") != 3:
            fail("single pass must read the 3 source windows directly and keep the 45 Mb/s cap")
        overlap = sum(round(d * q.OUTPUT_FPS) for _, d in editor._pair_transitions(3, transitions))
        want = sum(expected) - overlap
        n = frames(reel)
        if abs(n - want) > 1:
            fail(f"reel must have the timeline's frame count ({want}), got {n}")
        # 3. registry emptied
        if any(q.virtual_clip(c) for c in clips):
            fail("deferred clips must be forgotten after compile")

        # 4. a failing single pass falls back to per-clip encode and still yields the reel
        runs.clear()
        clips = [q._render_clip(src, ev, 450 + i, dec, defer=q.single_pass_enabled()) for i, (ev, dec) in enumerate(jobs)]
        good_expand = editor._finalize_compile_command

        def broken_expand(cmd):
            expanded = good_expand(cmd)
            if expanded is not cmd:  # only the single-pass command is broken
                at = expanded.index("-filter_complex") + 1
                expanded = [*expanded[:at], expanded[at] + ";[vclip0]not_a_real_filter[x]", *expanded[at + 1:]]
            return expanded

        editor._finalize_compile_command = broken_expand
        try:
            out2 = os.path.join(tmp, "reel_fallback.mp4")
            reel2 = editor.compile_reel(clips, "", out2, sport="surfing", transitions=transitions, fps=30)
        finally:
            editor._finalize_compile_command = good_expand
        if not reel2 or not os.path.exists(reel2):
            fail("a failed single pass must fall back to per-clip encode and still produce the reel")
        if len(runs) != 1 + 3 + 1:
            fail(f"fallback should be: failed single pass, 3 clip encodes, 1 compile; saw {len(runs)} runs")
        if abs(frames(reel2) - want) > 3:
            fail(f"fallback reel frame count {frames(reel2)} too far from {want}")
        for c in clips:
            if os.path.exists(c):
                os.remove(c)

        # 5. opt-outs keep the per-clip path
        import config

        config.QA_CROP_CHECK = True
        try:
            if q.single_pass_enabled():
                fail("per-clip QA needs real clip files: single pass must be off when QA_CROP_CHECK is on")
        finally:
            config.QA_CROP_CHECK = False
        os.environ["SPORTREEL_SINGLE_PASS_RENDER"] = "0"
        try:
            runs.clear()
            clip = q._render_clip(src, jobs[1][0], 499, jobs[1][1], defer=q.single_pass_enabled())
            if not clip or not os.path.exists(clip) or len(runs) != 1:
                fail("SPORTREEL_SINGLE_PASS_RENDER=0 must encode the clip file as before")
        finally:
            os.environ.pop("SPORTREEL_SINGLE_PASS_RENDER", None)

    print("single-pass render contract ok (one ffmpeg run per reel, exact timeline, safe fallback)")


if __name__ == "__main__":
    main()

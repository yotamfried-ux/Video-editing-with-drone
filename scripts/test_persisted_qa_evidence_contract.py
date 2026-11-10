#!/usr/bin/env python3
"""A run whose perception comes from the sidecar cache reuses the persisted QA evidence copy.

Run 42857524999: every analysis was cached, so no single decode ran, and QA cut each evidence window from the
4K source while the next reel rendered (28.2 s vs 4.5 s per 19 s window on 4 vCPU). Real ffmpeg + OpenCV.
"""
from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="evid-") as tmp:
        os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, "llm-cache")
        os.environ["TMP_DIR"] = os.path.join(tmp, "run1")
        os.makedirs(os.environ["TMP_DIR"])
        src1 = os.path.join(tmp, "dl1", "DJI_0151_D.MP4")
        os.makedirs(os.path.dirname(src1))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", src1], check=True)
        from pipeline.perception import single_decode as sd

        decode = sd.prepare_single_decode(src1, os.environ["TMP_DIR"], write_proxy=False)
        if decode.get("mode") != "single_decode" or not decode.get("evidence"):
            raise SystemExit(f"single decode did not produce an evidence copy: {decode.get('reason')}")
        fresh = decode["evidence"]
        persisted = sd._persistent_evidence_path(src1)
        if not persisted or not os.path.exists(persisted) or not filecmp.cmp(fresh, persisted, shallow=False):
            raise SystemExit("the evidence copy must be persisted (byte-identical) in the LLM cache dir")
        sd.cleanup(decode)

        # Next run: fresh TMP_DIR, the source downloaded again (new path, new mtime), perception from cache.
        os.environ["TMP_DIR"] = os.path.join(tmp, "run2")
        os.makedirs(os.environ["TMP_DIR"])
        src2 = os.path.join(tmp, "dl2", "DJI_0151_D.MP4")
        os.makedirs(os.path.dirname(src2))
        shutil.copyfile(src1, src2)
        restored = sd.evidence_copy_for(src2)
        if not restored or not filecmp.cmp(restored, persisted, shallow=False):
            raise SystemExit("a later run must restore the persisted copy for the same source content")

        import pipeline.source_evidence as se

        inputs = []
        real_run = subprocess.run

        def spy(cmd, *a, **k):
            if isinstance(cmd, list) and cmd and cmd[0] == "ffmpeg" and "-i" in cmd:
                inputs.append(cmd[cmd.index("-i") + 1])
            return real_run(cmd, *a, **k)

        se.subprocess.run = spy
        clips = se.make_source_clips({"source_windows": [{"source": src2, "source_start": 0.5, "source_end": 2.0}]})
        se.subprocess.run = real_run
        if not clips or inputs != [restored]:
            raise SystemExit(f"QA must cut from the restored evidence copy, not the source; ffmpeg inputs: {inputs}")

        other = os.path.join(tmp, "dl2", "DJI_0152_D.MP4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=25:duration=3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", other], check=True)
        if sd.evidence_copy_for(other) is not None:
            raise SystemExit("different source bytes must not reuse another source's evidence copy")
    print("persisted QA evidence contract ok (restored by content hash; QA cut from the copy, not the source)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

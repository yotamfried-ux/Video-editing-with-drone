#!/usr/bin/env python3
"""Contract: each source is decoded ONCE for perception + the Gemini proxy, with frame-exact evidence.

Run 42474968394 spent 18,290 s in yolo_perception (8 sources hit the 1200 s timeout): the 4K source was decoded
for the primary pass, re-decoded with a keyframe seek PER SAMPLED FRAME for the high-res escalation, and decoded
again for the Gemini proxy. This contract pins the single-decode replacement with real ffmpeg + OpenCV:

1. one ffmpeg run writes a near-lossless intermediate with the SAME frame count and the Gemini proxy;
2. the pre-made proxy is only claimable for the exact source file it was made from;
3. the sequential escalation reader returns pixel-identical frames, in the same order, as seek-per-frame;
4. boxes measured on the intermediate map back to source pixels and source frame dimensions.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"single-decode perception contract FAILED: {msg}")


def main() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        fail("ffmpeg/ffprobe are required (the production pipeline always has them)")
    import cv2  # noqa: F401  - required: the detector reads frames through OpenCV

    from pipeline.perception import single_decode as sd

    with tempfile.TemporaryDirectory(prefix="sportreel-single-decode-") as tmp:
        os.environ["TMP_DIR"] = os.path.join(tmp, "dtor")
        src = os.path.join(tmp, "DJI_test_0001_D.MP4")
        # 2560x1440 (wider than the 1280 intermediate), long GOP + B-frames like drone footage, 90 frames.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=2560x1440:rate=30:duration=3",
             "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-bf", "3", "-pix_fmt", "yuv420p", src],
            check=True,
        )

        decode = sd.prepare_single_decode(src, os.path.join(tmp, "work"))
        if decode.get("mode") != "single_decode":
            fail(f"expected single_decode mode, got {decode!r}")
        if decode["frame_count"] != 90:
            fail(f"intermediate must keep every source frame (90), got {decode['frame_count']}")
        if (decode["intermediate_width"], decode["intermediate_height"]) != (1280, 720):
            fail(f"intermediate must be 1280x720, got {decode['intermediate_width']}x{decode['intermediate_height']}")
        if (decode["scale_x"], decode["scale_y"]) != (2.0, 2.0):
            fail(f"scale back to source must be exact, got {decode['scale_x']}, {decode['scale_y']}")
        proxy = decode.get("proxy")
        if not proxy or not os.path.exists(proxy) or os.path.basename(proxy) != "proxy_DJI_test_0001_D.mp4":
            fail(f"Gemini proxy must be written from the same decode under the analyzer's name, got {proxy!r}")

        # 1b. The QA evidence copy (1280 px, native fps) comes from the same decode; QA cuts its windows from it.
        evidence = sd.evidence_copy_for(src)
        if not evidence:
            fail("the single decode must also write the 1280 px QA evidence copy, bound to its source")
        from pipeline import source_evidence

        ran: list[list[str]] = []
        real_run = source_evidence.subprocess.run

        def spy(cmd, *a, **k):
            ran.append(cmd)
            return real_run(cmd, *a, **k)

        source_evidence.subprocess.run = spy
        try:
            ctx = {"source_windows": [{"source": src, "source_start": 2.5, "source_end": 3.0}]}
            got = source_evidence.make_source_clips(ctx, os.path.join(tmp, "qa"))
            if not got or ran[0][ran[0].index("-i") + 1] != evidence:
                fail("QA source evidence must be cut from the evidence copy, not the original 4K source")
            ref = os.path.join(tmp, "ref_qa.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", src, "-t", "4.5", "-vf", "scale='min(1280,iw)':-2",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-an", ref], check=True)
            psnr = subprocess.run(["ffmpeg", "-i", got[0], "-i", ref, "-lavfi", "psnr", "-f", "null", "-"],
                                  capture_output=True, text=True).stderr
            avg = float(psnr.rsplit("average:", 1)[1].split()[0]) if "average:" in psnr else 0.0
            if avg < 38.0:
                fail(f"evidence clip from the copy must match the 4K-cut clip closely, PSNR {avg:.1f} dB")
        finally:
            source_evidence.subprocess.run = real_run

        # 2. The proxy is bound to this exact source; a modified source must not reuse it.
        os.utime(src, ns=(os.stat(src).st_atime_ns, os.stat(src).st_mtime_ns + 1_000_000_000))
        if sd.claim_premade_proxy(src) is not None:
            fail("a proxy made for a different source version must never be claimed")
        if sd.evidence_copy_for(src) is not None:
            fail("an evidence copy made for a different source version must never be used")
        decode2 = sd.prepare_single_decode(src, os.path.join(tmp, "work"))
        if sd.claim_premade_proxy(src) != decode2.get("proxy"):
            fail("the proxy made for this exact source must be claimable once")
        if sd.claim_premade_proxy(src) is not None:
            fail("a claimed proxy marker must be consumed (claimable exactly once)")
        sd.discard_premade_proxy(src)
        if os.path.exists(decode2["proxy"]):
            fail("discard_premade_proxy must delete an unused proxy")

        # 3. Sequential reader == seek-per-frame reader (same frames, same order, pixel-identical).
        spec = importlib.util.spec_from_file_location("gps", ROOT / "scripts" / "generate_perception_sidecar.py")
        gps = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(gps)
        import cv2
        import numpy as np

        targets = [*range(3, 40, 2), *range(30, 50, 2), *range(70, 90, 2)]  # overlap (backward) + forward gap
        cap = cv2.VideoCapture(decode2["frames_path"])
        seq = list(gps._read_frames_sequentially(cap, targets, seek_gap=8))
        cap.release()
        if [i for i, _ in seq] != targets:
            fail("sequential reader must yield exactly the requested frames in the requested order")
        cap = cv2.VideoCapture(decode2["frames_path"])
        for idx, frame in seq:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, ref = cap.read()
            if not ok or not np.array_equal(ref, frame):
                fail(f"frame {idx} differs between sequential read and seek+read")
        cap.release()

        # 4. Boxes back to source coordinates and dimensions.
        mapped = sd.to_source_coordinates(
            [{"bbox_xyxy": [10.0, 20.0, 110.0, 220.0], "frame_width": 1280, "frame_height": 720, "track_id": 1}],
            decode2,
        )[0]
        if mapped["bbox_xyxy"] != [20.0, 40.0, 220.0, 440.0] or (mapped["frame_width"], mapped["frame_height"]) != (2560, 1440):
            fail(f"boxes must map back to 2560x1440 source pixels, got {json.dumps(mapped)}")

        sd.cleanup(decode)
        sd.cleanup(decode2)
        if any(p.name.startswith("perception_") for p in Path(tmp, "work").iterdir()):
            fail("intermediates must be deleted after perception")

        # A source no wider than the intermediate keeps the direct path (nothing to gain).
        small = os.path.join(tmp, "small.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=1",
                        "-c:v", "libx264", "-preset", "ultrafast", small], check=True)
        if sd.prepare_single_decode(small, os.path.join(tmp, "work")).get("mode") != "direct":
            fail("sources <=1280 px wide must use the direct path")

    print("single-decode perception contract ok (one decode, frame-exact intermediate, bound proxy, identical frames)")


if __name__ == "__main__":
    main()

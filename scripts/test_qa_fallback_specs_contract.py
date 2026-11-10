#!/usr/bin/env python3
"""Run 42857524999 regressions on the QA fallback path (real ffprobe, no network).

* One Gemini call failed with "ServerError: 500 INTERNAL"; _with_retry did not treat 500 as transient, so the
  reel fell back to the base tiered QA on the first attempt.
* That fallback rejected the real 2160x3840 / 30 fps reel as TECHNICAL_FRAME_RATE_NOT_30FPS: the specs it
  checked came from get_reel_specs, which had no fps, and the 4K/30 policy read the missing value as 0.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from integrations.ffmpeg import get_reel_specs
    from pipeline import bootstrap

    bootstrap.install_pre_orchestrator_patches()  # production install order
    import pipeline.quality_preserving_framing as q
    import pipeline.stages.analyzer as analyzer
    from pipeline.tiered_qa_gate import run_tier1_local_qa_checks

    with tempfile.TemporaryDirectory(prefix="qa-fallback-") as tmp:
        reel = os.path.join(tmp, "MULTI_reel.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=size={q.OUTPUT_WIDTH}x{q.OUTPUT_HEIGHT}:rate={q.OUTPUT_FPS}:duration=1",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", reel], check=True)
        if abs(float(get_reel_specs(reel).get("fps") or 0) - q.OUTPUT_FPS) > 0.1:
            raise SystemExit("get_reel_specs must report the reel's frame rate")
        specs, _ok, _issues = analyzer._check_technical_compliance(reel)
        tier1 = run_tier1_local_qa_checks(reel, [], specs={"pass": True, **specs})
        types = {d.get("type") for d in tier1.get("defects", [])}
        if "TECHNICAL_FRAME_RATE_NOT_30FPS" in types:
            raise SystemExit("a real 30 fps 4K reel was rejected as not 30 fps (run 42857524999)")
        slow = os.path.join(tmp, "MULTI_25fps.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=size={q.OUTPUT_WIDTH}x{q.OUTPUT_HEIGHT}:rate=25:duration=1",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", slow], check=True)
        specs, _ok, _issues = analyzer._check_technical_compliance(slow)
        tier1 = run_tier1_local_qa_checks(slow, [], specs={"pass": True, **specs})
        if "TECHNICAL_FRAME_RATE_NOT_30FPS" not in {d.get("type") for d in tier1.get("defects", [])}:
            raise SystemExit("a real 25 fps reel must still fail the 30 fps policy")

    class ServerError(Exception):
        pass

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ServerError("500 INTERNAL. {'error': {'code': 500, 'message': 'Failed to convert server response to JSON', 'status': 'INTERNAL'}}")
        return "ok"

    if analyzer._with_retry(flaky, base_delay=0) != "ok" or calls["n"] != 2:
        raise SystemExit("a Gemini 500 INTERNAL must be retried (run 42857524999)")

    def bad_request():
        calls["n"] += 1
        raise ValueError("400 INVALID_ARGUMENT: request contains an invalid argument")

    calls["n"] = 0
    try:
        analyzer._with_retry(bad_request, base_delay=0)
    except ValueError:
        pass
    if calls["n"] != 1:
        raise SystemExit("a client error (400) must not be retried")
    print("QA fallback specs contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Opt-in live Gemini video QA against generated synthetic MP4 only."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

def main():
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY unavailable; live qualification was NOT run")
    with tempfile.TemporaryDirectory(prefix="sportreel-gemini-live-") as folder:
        root = Path(folder)
        reel = root / "synthetic_two_subjects.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=12:d=8",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-vf", "drawbox=x=100:y=400:w=250:h=500:color=green:t=fill,"
                   "drawbox=x=700:y=400:w=250:h=500:color=red:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(reel)
        ], check=True, timeout=120)
        os.environ["QA_RESULTS_FILE"] = str(root / "qa.jsonl")
        import config
        config.QA_RESULTS_FILE = str(root / "qa.jsonl")
        from pipeline.stages.analyzer import qa_check_reel
        result = qa_check_reel(str(reel), sport="synthetic visual QA fixture")
        assert result["verdict"] in ("PASS", "FAIL")
        assert result.get("overall") != "QA provider unavailable; review required", "Gemini unavailable"
        assert result.get("engagement_score") is not None
        assert (root / "qa.jsonl").exists(), "Missing persisted QA evidence"
        print(json.dumps({
            "fixture": "synthetic rectangles (not sports ground truth)",
            "provider_invoked": True,
            "verdict": result["verdict"],
            "engagement_score": result["engagement_score"],
            "technical": result.get("technical", {}).get("pass"),
            "evidence_persisted": True,
        }))

if __name__ == "__main__":
    main()

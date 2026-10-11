#!/usr/bin/env python3
"""Isolated SportReel QA -> manifest qualification on real rendered MP4.

Real FFmpeg renderer, actual manifest and QA evidence policy. QA verdicts are
controlled inputs, not an LLM or visual quality judgment. No upload or providers.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_pipeline_real_mp4_renderer import run, probe


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sportreel-qa-manifest-") as d:
        folder = Path(d)
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(folder / "manifest.json")
        sys.modules["config"] = types.SimpleNamespace(
            TMP_DIR=str(folder), QUALITY_LOG_FILE=str(folder / "quality.jsonl"),
            MIN_SOURCE_HEIGHT=1440, SLOWMO_INTERPOLATE=False,
            MAX_CUT_WORKERS=2, ATHLETE_TEXT_OVERLAY=False)
        from pipeline.stages import editor
        from pipeline import publishable_reel_policy as policy
        from pipeline.publishable_qa_evidence import record_qa_result, apply_final_qa_evidence

        policy.reset_manifest()
        source = folder / "two_subjects.mp4"
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:r=30:d=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=6",
            "-vf", "drawbox=x=140:y=300:w=450:h=450:color=green:t=fill,"
                   "drawbox=x=1330:y=300:w=450:h=450:color=red:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(source))
        info = {"width": 1920, "height": 1080, "fps": 30.0,
                "zoom_headroom": 1.0, "can_slowmo": False}
        paths = []
        for index, cx in enumerate((.20, .80)):
            event = {"start": 0, "end": 4, "type": "highlight", "score": 6,
                     "crop_x": cx, "crop_y": .5,
                     "athlete_id": "surfer_" + str(index),
                     "edit": {"zoom": 1.0, "slowmo": False}}
            output = editor.cut_clip(str(source), event, index,
                                     sport="surfing", source_info=info, target_fps=30)
            assert output and Path(output).is_file()
            assert probe(Path(output))["codec_name"] == "h264"
            paths.append((output, event))
        # Assemble actual final reels with music (cut_clip intermediates are silent).
        music = folder / "music.wav"
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=12",
            "-c:a", "pcm_s16le", str(music))
        final_paths = []
        for index, (clip, event) in enumerate(paths):
            final_path = folder / f"final_reel_{index}.mp4"
            reel = editor.compile_reel([clip], "", str(final_path),
                                        sport="surfing", music_path=str(music), fps=30)
            assert reel and Path(reel).is_file(), "final reel compilation failed"
            audio = run("ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=codec_name", "-of", "csv=p=0", reel)
            assert "aac" in audio.stdout, "final reel missing AAC audio"
            assert probe(Path(reel))["codec_name"] == "h264"
            final_paths.append((reel, event))
        paths = final_paths
        specs = {"duration": 4, "width": 1080, "height": 1920,
                 "aspect": 9 / 16, "has_audio": True}
        for index, (path, event) in enumerate(paths):
            label = "surfer " + str(index)
            policy.record_athlete_outcome(
                sport="surfing", athlete_label=label,
                final_reels=[path], events_by_reel={path: [event]},
                flagged_paths=set(), specs_by_path={path: specs})
            token = "isolated-qa-" + str(index)
            if index == 0:
                record_qa_result(path, {"verdict": "PASS", "overall": "verified fixture"},
                                 invocation_token=token)
            else:
                record_qa_result(path, {"verdict": "FAIL", "overall": "identity switch",
                                        "defects": [{"type": "IDENTITY_SWITCH",
                                                     "severity": "critical"}]},
                                 invocation_token=token)
            blocked = apply_final_qa_evidence(
                sport="surfing", athlete_label=label, final_reels=[path],
                invocation_token=token)
            assert (path in blocked) == (index == 1), blocked
        # QA retry must clear its own stale FAIL reason, but not unrelated blockers.
        policy_manifest_path = Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"])
        before_retry = json.loads(policy_manifest_path.read_text())
        failing_row = next(r for r in before_retry["athletes"]
                           if r["athlete_label"] == "surfer 1")
        assert any(reason.startswith("final_qa_failed:")
                   for reason in failing_row["blocking_reasons"])
        retry_path = paths[1][0]
        retry_token = "isolated-qa-retry-1"
        record_qa_result(retry_path, {"verdict": "PASS", "overall": "verified retry"},
                         invocation_token=retry_token)
        assert not apply_final_qa_evidence(
            sport="surfing", athlete_label="surfer 1",
            final_reels=[retry_path], invocation_token=retry_token)
        after_retry = json.loads(policy_manifest_path.read_text())
        retry_row = next(r for r in after_retry["athletes"]
                         if r["athlete_label"] == "surfer 1")
        assert not any(reason.startswith(("final_qa_failed:", "missing_final_qa_evidence:"))
                       for reason in retry_row["blocking_reasons"]), retry_row
        assert retry_row["parts"][0]["qa_verdict"] == "PASS", retry_row
        assert retry_row["parts"][0]["render_ready"] is True, retry_row
        manifest = json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())
        assert len(manifest["athletes"]) == 2, manifest
        by_label = {r["athlete_label"]: r["parts"][0] for r in manifest["athletes"]}
        assert by_label["surfer 0"]["qa_verdict"] == "PASS"
        assert by_label["surfer 0"]["qa_evidence_recorded"] is True
        assert by_label["surfer 0"]["render_ready"] is True
        assert by_label["surfer 1"]["qa_verdict"] == "PASS"
        assert by_label["surfer 1"]["render_ready"] is True
        assert "final_qa_failed" not in by_label["surfer 1"]["technical_issues"]
        # A PASS must never become publishable until upload is confirmed.
        assert manifest["summary"]["publishable_athlete_count"] == 0
        assert manifest["summary"]["coverage_gap_count"] == 2
        print(json.dumps({"result": "PASS",
                          "actual_renderer": True, "actual_reel_compiler": True,
                          "verified_aac_audio": True, "actual_qa_manifest_policy": True,
                          "llm_qa_executed": False, "real_detector_executed": False,
                          "upload_executed": False, "rendered_reels": len(paths),
                          "positive_qa": "render_ready_not_published",
                          "negative_qa": "blocked_before_retry",
                          "qa_retry": "stale_blocker_cleared",
                          "missing_upload": "fail_closed"}, indent=2))


if __name__ == "__main__":
    main()

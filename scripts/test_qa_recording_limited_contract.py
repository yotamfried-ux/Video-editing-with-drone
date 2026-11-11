#!/usr/bin/env python3
"""A ride the camera stopped recording is not an editing defect, and must not block a reel.

Run 42891165218: all 12 reels were "QA failed - re-edit required / approval blocked". Every one carried
PREMATURE_CUT (always blocking in pipeline.qa_gate_policy), and on 19 of 22 findings QA itself wrote "due to
the camera recording ending, not an editing choice": the clip already ran to the last recorded frame, so no
re-edit could add anything. The decision is made from the measured windows, not from the model's wording:

1. a cut finding on a clip that reaches the end of its recording becomes RECORDING_ENDS_MID_ACTION
   (severity "info"), which neither fails the reel nor blocks approval;
2. a cut finding on a clip with footage left after it stays a blocking PREMATURE_CUT;
3. the reviewer cannot hide a real cut behind the new code: RECORDING_ENDS_MID_ACTION on a clip with footage
   left is turned back into PREMATURE_CUT;
4. every clip of the draft is described to the reviewer, including clips beyond the 4 evidence videos.

No network or Gemini: the provider is a fake that records the request parts. Real ffmpeg for the sources.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"QA recording-limited contract FAILED: {msg}")


def _source(path: str, seconds: float) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x360:rate=30:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", path], check=True)


def _analyzer(sent: list, response: dict, duration: float):
    class Resp:
        text = json.dumps(response)

    class Model:
        def generate_content(self, parts, request_options=None):
            sent.append(list(parts))
            return Resp()

    class GenAI:
        def GenerativeModel(self, model_name):
            return Model()

    class Analyzer:
        _QA_REEL_PROMPT = "qa"
        _QA_REEL_MODEL = "fake"
        genai = GenAI()

        def _check_technical_compliance(self, reel):
            return {"duration": duration, "width": 2160, "height": 3840}, True, []

        def _upload_video(self, path):
            return {"uploaded": os.path.basename(path)}

        def _delete_video(self, item):
            pass

        def _with_retry(self, fn):
            return fn()

        def _persist_qa_result(self, *args):
            pass

    return Analyzer()


def main() -> int:
    import pipeline.source_evidence_runner as runner
    from pipeline import qa_gate_policy

    limited = getattr(runner, "RECORDING_LIMITED_TYPE", None)
    if limited != "RECORDING_ENDS_MID_ACTION":
        fail("the runner must define RECORDING_LIMITED_TYPE")
    if limited in qa_gate_policy.BLOCKING_DEFECT_TYPES or limited in qa_gate_policy.ALWAYS_BLOCKING_DEFECT_TYPES:
        fail("a camera-limited ending must not be a blocking defect type")

    with tempfile.TemporaryDirectory(prefix="qa-rec-limited-") as tmp:
        os.environ["TMP_DIR"] = tmp
        names = ["DJI_20260720160658_0097_D.MP4", "DJI_20260720164734_0151_D.MP4", "DJI_20260720162806_0126_D.MP4",
                 "DJI_20260720163004_0131_D.MP4", "DJI_20260720163559_0140_D.MP4"]
        sources = [os.path.join(tmp, name) for name in names]
        _source(sources[0], 10.0)   # clip 1: 2.0-10.0, runs to the last frame
        _source(sources[1], 7.6)    # clip 2: 0.0-5.0, 2.6 s of footage left after the cut
        for path in sources[2:]:
            _source(path, 6.0)      # clips 3-5: 1.0-6.0, run to the last frame

        # ── A single-clip reel that ends where the recording ends (0097 in the run) ──────────────────────
        context = {"reel": "reel.mp4", "source_windows": [
            {"source": sources[0], "source_start": 2.0, "source_end": 10.0,
             "rendered_timeline_start": 0.0, "rendered_timeline_end": 8.0}]}
        sent: list = []
        response = {"content": {"hook": 7}, "engagement_score": 65, "overall": "ok", "defects": [
            {"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 8,
             "note": "The ride is cut before its natural completion; a limitation of the camera recording."}],
            "clips": [{"clip_index": 1, "opens_on_action": True, "seconds_to_first_action": 0.2,
                       "ending": "cut_by_edit", "dead_seconds": 0}]}
        result = runner.with_source_evidence(_analyzer(sent, response, 8.0), lambda *a, **k: {"verdict": "PASS"},
                                             "reel.mp4", sport="surfing", context=context)
        types = [d.get("type") for d in result.get("defects", [])]
        if types != [limited]:
            fail(f"a cut finding on a clip that reaches the recording end must become {limited}, got {types}")
        note = result["defects"][0]
        if note.get("severity") != "info" or note.get("original_type") != "PREMATURE_CUT" or note.get("actionable") is not False:
            fail(f"the note must keep what QA reported and be non-actionable: {note}")
        if result.get("verdict") != "PASS" or result.get("qa_review_required"):
            fail(f"a 65-point reel whose only finding is the end of the recording must pass: {result.get('verdict')}")
        if qa_gate_policy.critical_defects(result) or qa_gate_policy.approval_blocked_reasons(result):
            fail("the end of a recording must not block approval or ask for a re-edit")
        _diag, blocked = qa_gate_policy.build_final_qa_diagnostics(result, retry_count=0, reel_path="reel.mp4")
        if blocked:
            fail("the final QA gate must not hold this reel for review")
        reviews = result.get("clip_reviews") or []
        if len(reviews) != 1 or reviews[0].get("ending") != "cut_by_camera" or reviews[0].get("ending_corrected_from") != "cut_by_edit":
            fail(f"a reviewer's 'cut_by_edit' on a clip at the recording end must be corrected: {reviews}")
        prompt = sent[0][-1]
        if "ALREADY RUNS TO THE LAST RECORDED FRAME" not in prompt or limited not in prompt or '"clips"' not in prompt:
            fail("the reviewer must be told which clips cannot be extended and asked for per-clip verdicts")

        # ── A five-clip reel: one real cut among camera-limited endings ──────────────────────────────────
        windows = [(sources[0], 2.0, 10.0), (sources[1], 0.0, 5.0), (sources[2], 1.0, 6.0),
                   (sources[3], 1.0, 6.0), (sources[4], 1.0, 6.0)]
        timeline, at = [], 0.0
        for src, start, end in windows:
            timeline.append({"source": src, "source_start": start, "source_end": end,
                             "rendered_timeline_start": at, "rendered_timeline_end": at + (end - start)})
            at += end - start
        context = {"reel": "reel5.mp4", "source_windows": timeline}   # clip ends: 8, 13, 18, 23, 28
        sent = []
        response = {"content": {}, "engagement_score": 70, "overall": "ok", "defects": [
            {"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 8, "note": "ride still going"},
            {"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 13, "note": "cut just before the fall"},
            {"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 28, "note": "source video ends mid-action"},
            {"type": "DEAD_TIME", "severity": "minor", "at_seconds": 15, "note": "nothing happens"}]}
        result = runner.with_source_evidence(_analyzer(sent, response, at), lambda *a, **k: {"verdict": "PASS"},
                                             "reel5.mp4", sport="surfing", context=context)
        by_time = {d.get("at_seconds"): d.get("type") for d in result.get("defects", [])}
        if by_time != {8: limited, 13: "PREMATURE_CUT", 28: limited, 15: "DEAD_TIME"}:
            fail(f"only the clip with footage left (ends at 13 s of the draft) keeps PREMATURE_CUT, got {by_time}")
        blocking = [d.get("at_seconds") for d in qa_gate_policy.critical_defects(result)]
        if blocking != [13]:
            fail(f"the real cut must still block, and only it: {blocking}")
        facts = result.get("draft_clip_facts") or []
        if len(facts) != 5 or not facts[4].get("reaches_recording_end") or facts[1].get("reaches_recording_end"):
            fail(f"all five clips must be measured, beyond the 4 evidence videos: {facts}")
        if "clip 5:" not in sent[0][-1] or "2.6s of footage exists after the cut" not in sent[0][-1]:
            fail("the reviewer must get the facts of every clip, including the footage left after a cut")

        # ── The reviewer blames the camera where footage exists: still a real cut ─────────────────────────
        sent = []
        response = {"content": {}, "engagement_score": 70, "overall": "ok", "defects": [
            {"type": limited, "severity": "minor", "at_seconds": 13, "note": "camera stopped"},
            {"type": limited, "severity": "critical", "at_seconds": 28, "note": "camera stopped"}]}
        result = runner.with_source_evidence(_analyzer(sent, response, at), lambda *a, **k: {"verdict": "PASS"},
                                             "reel5.mp4", sport="surfing", context=context)
        by_time = {d.get("at_seconds"): (d.get("type"), d.get("severity")) for d in result.get("defects", [])}
        if by_time.get(13, ("",))[0] != "PREMATURE_CUT":
            fail(f"{limited} on a clip with footage left must be treated as PREMATURE_CUT, got {by_time}")
        if by_time.get(28) != (limited, "info"):
            fail(f"a genuine camera-limited ending is a note whatever severity the reviewer gave it, got {by_time}")
        if [d.get("at_seconds") for d in qa_gate_policy.critical_defects(result)] != [13]:
            fail("only the real cut may block")

        # ── A cut that cannot be placed on a clip is left alone ───────────────────────────────────────────
        untimed = {"reel": "reel2.mp4", "source_windows": [
            {"source": sources[0], "source_start": 2.0, "source_end": 10.0},
            {"source": sources[1], "source_start": 0.0, "source_end": 5.0}]}
        kept = runner.reclassify_recording_limited(
            [{"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 8}], runner.draft_clip_facts(untimed))
        if [d.get("type") for d in kept] != ["PREMATURE_CUT"]:
            fail("without a draft timeline a cut on a mixed reel must stay a blocking finding")

    print("QA recording-limited contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

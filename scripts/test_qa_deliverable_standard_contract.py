#!/usr/bin/env python3
"""Final QA judges a reel as the product the athlete pays for; one good ride is a complete reel.

Run 42891165218: 5 reels of one or two clean rides failed final QA on engagement 45-55 with no critical defect.
Their weak dimensions were loopability (2-5), payoff and cut pacing, which a single uninterrupted ride scores
low on by construction. The athlete pays for the record of their own ride, not for a viral edit.

1. The reviewer is told the product, and that a single clear complete ride is complete; loopability is
   informational; it returns `deliverable_score` next to `engagement_score`.
2. Final QA passes on `deliverable_score` (falls back to `engagement_score` when the reviewer gives none).
3. Critical defects and technical failures still fail a reel whatever its score.
4. The tier-3 borderline audit and the manifest use the same score; the QA cache key changes with the policy.
5. The ride-coverage report names people the analyzer gave no ride to and long moving tracks outside every ride.
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
    raise SystemExit(f"QA deliverable standard contract FAILED: {msg}")


def _source(path: str, seconds: float) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x360:rate=30:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", path], check=True)


def _analyzer(response: dict, duration: float):
    class Resp:
        text = json.dumps(response)

    class Model:
        def generate_content(self, parts, request_options=None):
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


def check_prompt() -> None:
    text = (ROOT / "pipeline" / "stages" / "analyzer.py").read_text(encoding="utf-8")
    start = text.index('_QA_REEL_PROMPT = """')
    prompt = text[start:text.index('"""', start + 25)]
    for needle in ("bought by the athlete", "single", "complete product", "deliverable_score",
                   "Informational only", "One good ride scores", "is not slow pacing"):
        if needle not in prompt:
            fail(f"the final QA prompt must state the product standard ({needle!r} missing)")
    if "fast cuts" in prompt:
        fail("pacing must not ask for fast cuts: an uninterrupted ride needs none")


def check_gate_score() -> None:
    from pipeline import qa_gate_policy as gate

    os.environ.pop("QA_DELIVERABLE_THRESHOLD", None)
    os.environ.pop("QA_ENGAGEMENT_THRESHOLD", None)
    if gate.qa_pass_threshold() != 60:
        fail("the default pass threshold stays 60")
    os.environ["QA_ENGAGEMENT_THRESHOLD"] = "55"
    if gate.qa_pass_threshold() != 55:
        fail("an operator's QA_ENGAGEMENT_THRESHOLD keeps working")
    os.environ["QA_DELIVERABLE_THRESHOLD"] = "65"
    if gate.qa_pass_threshold() != 65:
        fail("QA_DELIVERABLE_THRESHOLD takes precedence")
    os.environ.pop("QA_DELIVERABLE_THRESHOLD")
    os.environ.pop("QA_ENGAGEMENT_THRESHOLD")
    if gate.qa_gate_score({"deliverable_score": 78, "engagement_score": 50}) != 78:
        fail("the gate score is the deliverable score")
    if gate.qa_gate_score({"engagement_score": 64}) != 64 or gate.qa_gate_score({"deliverable_score": None, "engagement_score": 64}) != 64:
        fail("without a deliverable score the engagement score decides, as before")
    if gate.qa_gate_score({}) != 0 or gate.qa_gate_score({"deliverable_score": "x"}) != 0:
        fail("no usable score is 0")


def check_runner(tmp: str) -> None:
    import pipeline.source_evidence_runner as runner
    from pipeline import qa_gate_policy as gate

    source = os.path.join(tmp, "DJI_20260720161907_0115_D.MP4")
    _source(source, 10.0)
    context = {"reel": "reel.mp4", "source_windows": [
        {"source": source, "source_start": 0.5, "source_end": 10.0,
         "rendered_timeline_start": 0.0, "rendered_timeline_end": 9.5}]}

    def run(response: dict) -> dict:
        return runner.with_source_evidence(_analyzer(response, 9.5), lambda *a, **k: {"verdict": "PASS"},
                                           "reel.mp4", sport="surfing", context=context)

    single_ride = {"content": {"hook": 8, "pacing": 6, "payoff": 5, "clarity": 8, "loopability": 2},
                   "defects": [], "engagement_score": 55, "deliverable_score": 76, "overall": "one clean ride"}
    result = run(single_ride)
    if result.get("verdict") != "PASS":
        fail(f"a single clean ride (deliverable 76, engagement 55, loopability 2) must pass: {result.get('verdict')}")
    if result.get("deliverable_score") != 76 or result.get("engagement_score") != 55 or result.get("gate_score") != 76:
        fail(f"both scores and the deciding one are kept: {result}")
    diagnostics = gate.build_qa_diagnostics(result, retry_count=0, decision="pass")
    if diagnostics.get("gate_score") != 76:
        fail("the QA diagnostics carry the deciding score")

    weak = {**single_ride, "deliverable_score": 45, "engagement_score": 70}
    if run(weak).get("verdict") != "FAIL":
        fail("a reel the athlete would not pay for fails even with a high engagement estimate")

    legacy = {k: v for k, v in single_ride.items() if k != "deliverable_score"}
    if run(legacy).get("verdict") != "FAIL":
        fail("a response without a deliverable score is judged on engagement (55 < 60), as before")

    defect = {**single_ride, "defects": [{"type": "IDENTITY_MISMATCH", "severity": "critical", "at_seconds": 3}]}
    if run(defect).get("verdict") != "FAIL":
        fail("a critical defect fails the reel whatever its deliverable score")


def check_tier3_and_manifest() -> None:
    from pipeline import tiered_qa_gate

    minor = [{"type": "DEAD_TIME", "severity": "minor"}, {"type": "SOFT_FOCUS", "severity": "minor"}]
    passing = {"verdict": "PASS", "engagement_score": 40, "deliverable_score": 80, "defects": minor}
    audited = tiered_qa_gate.run_tier3_exception_audit(passing, [{"start": 0, "end": 5}], engagement_threshold=60)
    if audited.get("verdict") != "PASS":
        fail("the borderline audit must read the deliverable score (80 is not borderline)")
    borderline = {**passing, "deliverable_score": 62, "engagement_score": 90}
    audited = tiered_qa_gate.run_tier3_exception_audit(borderline, [{"start": 0, "end": 5}], engagement_threshold=60)
    if audited.get("verdict") == "PASS":
        fail("a borderline deliverable score with two minor defects is still escalated")


def check_manifest_text() -> None:
    source = (ROOT / "pipeline" / "publishable_reel_policy.py").read_text(encoding="utf-8")
    if 'part.get("qa_deliverable_score")' not in source or "qa_pass_threshold()" not in source:
        fail("the manifest must report the deciding score against the deciding threshold")
    evidence = (ROOT / "pipeline" / "publishable_qa_evidence.py").read_text(encoding="utf-8")
    if 'part["qa_deliverable_score"]' not in evidence:
        fail("the publishable evidence must carry the deliverable score")


def check_cache_key() -> None:
    from pipeline import render_qa_cache

    if render_qa_cache.QA_POLICY_VERSION == "qa-policy-v2":
        fail("the QA cache policy version must change: cached verdicts were decided by the old standard")
    source = (ROOT / "pipeline" / "render_qa_cache.py").read_text(encoding="utf-8")
    if "qa-prompt-2026-11-07" in source or "deliverable_threshold" not in source:
        fail("the QA cache key must cover the new prompt and threshold")


def check_ride_coverage_report() -> None:
    from pipeline import performance_reel_policy as policy
    from pipeline.perception.schema import PerceptionDetection

    def det(track, t, x):
        return PerceptionDetection(source_video="v.mp4", frame_index=int(t * 30), time_sec=t,
                                   xyxy=(x, 400, x + 60, 520), frame_width=1920, frame_height=1080,
                                   confidence=0.9, class_id=0, class_name="person", tracker_id=track)

    detections = []
    detections += [det(1, 0.5 * i, 300 + 40 * i) for i in range(0, 26)]          # 0-12.5 s, rides (kept)
    detections += [det(2, 17 + 0.5 * i, 1500 - 35 * i) for i in range(0, 36)]    # 17-34.5 s, rides (not kept)
    detections += [det(3, 0.5 * i, 900 + (i % 2) * 4) for i in range(0, 60)]     # sits still for 30 s
    detections += [det(4, 20 + 0.5 * i, 200 + 60 * i) for i in range(0, 4)]      # 1.5 s: too short
    people = [{"id": "person_A", "description": "long dark hair, black tank top, white longboard",
               "events": [{"start": 3.5, "end": 12.5}]},
              {"id": "person_C", "description": "adult and child on one board", "events": [],
               "no_output_reason": "no_complete_action"}]
    candidates = policy.missed_ride_candidates(people, detections)
    if [c["track_id"] for c in candidates] != ["2"]:
        fail(f"only the long moving track outside every ride is a possible missed ride, got {candidates}")
    if candidates[0]["start"] != 17.0 or candidates[0]["covered"] != 0.0:
        fail(f"the candidate reports where it is and how much of it a ride covers: {candidates[0]}")
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        policy.report_ride_coverage("/x/DJI_0094_D.MP4", people, detections)
    text = buf.getvalue()
    if "person_C" not in text or "adult and child" not in text or "no_complete_action" not in text:
        fail("a person the analyzer gave no ride to must be named in the log with its reason")
    if "track 2 17.0-34.5s" not in text:
        fail("the possible missed ride must be printed with its time span")
    if "track 3" in text or "track 1 " in text:
        fail("a still or already-covered track is not a candidate")


def main() -> int:
    check_prompt()
    check_gate_score()
    with tempfile.TemporaryDirectory(prefix="qa-deliverable-") as tmp:
        os.environ["TMP_DIR"] = tmp
        check_runner(tmp)
    check_tier3_and_manifest()
    check_manifest_text()
    check_cache_key()
    check_ride_coverage_report()
    print("QA deliverable standard contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

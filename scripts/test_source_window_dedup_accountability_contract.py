#!/usr/bin/env python3
"""Regression for run 42814819534: one duplicate athlete failed the whole run's accountability gate.

Source 0095 had person_A (window 0.0-5.8) and person_B (window 0.0-5.0): the same surfer reported twice.
``dedupe_session`` correctly dropped person_B's event as a duplicate source window, but the selector candidate
ledger was captured BEFORE dedup, so person_B stayed "selected" with no draft and no reason. The coverage report
counted an unexplained gap (accountability 0.979 != 1.0) and the publishable gate failed the run.

This drives the real selector-runtime wrapper with the real ``dedupe_session`` and the real ledger -> selection
audit -> coverage report scripts, and requires the duplicate to end with an explicit rejection reason.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW = {
    "activity": "surfing",
    "persons": [
        {"id": "person_A", "description": "Stand-up paddle surfer in a white top on a white board",
         "events": [{"type": "wave_catch", "start": 0.0, "end": 5.8, "score": 8, "description": "rides a wave"}]},
        {"id": "person_B", "description": "Paddle boarder in white riding the same wave",
         "events": [{"type": "wave_catch", "start": 0.0, "end": 5.0, "score": 7, "description": "rides a wave"}]},
    ],
}


def fail(msg: str) -> None:
    raise SystemExit(f"source-window dedup accountability contract FAILED: {msg}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sportreel-dedup-acct-") as tmp:
        import config

        config.TMP_DIR = tmp
        source = "2026-10-03T12-19-53_DJI_20260720160431_0095_D.MP4"
        video = Path(tmp, source)
        video.write_bytes(b"not decoded in this test")

        analyzer = types.ModuleType("pipeline.stages.analyzer")
        analyzer._CHUNK_MAX_MINUTES = 8

        def parse(raw_text: str) -> dict:
            return json.loads(raw_text)

        def analyze_session(path: str) -> dict:
            return analyzer._parse_session(json.dumps(RAW))

        analyzer._parse_session = parse
        analyzer.analyze_session = analyze_session
        import pipeline.stages as stages

        sys.modules["pipeline.stages.analyzer"] = analyzer
        stages.analyzer = analyzer

        import pipeline.selector_candidate_runtime as runtime

        runtime.source_duration = lambda path: 30.0
        runtime.install()
        session = analyzer.analyze_session(str(video))

        kept = {p["id"]: [e["start"] for e in p.get("events", [])] for p in session["persons"]}
        if kept.get("person_B"):
            fail(f"precondition: dedupe_session should drop person_B's duplicate window, kept={kept}")

        payload = json.loads(Path(tmp, "selector_candidate_events.json").read_text(encoding="utf-8"))
        b = [c for c in payload["candidates"] if c.get("person_id") == "person_B"]
        if not b or b[0].get("selected") or b[0].get("discard_cause") != "duplicate_source_window_before_render":
            fail(f"person_B's candidate must be discarded as a duplicate source window, got {b}")
        a = [c for c in payload["candidates"] if c.get("person_id") == "person_A"]
        if not a or not a[0].get("selected"):
            fail("person_A's surviving candidate must stay selected")

        # Same downstream path as scripts/run_pipeline_with_diagnostics.sh (person_A rendered as a draft).
        trace = Path(tmp, "draft_decision_trace.json")
        trace.write_text(json.dumps({"schema_version": "sportreel.draft_decision_trace.v1", "drafts": [{
            "draft_name": "DRAFT_Stand-up paddle surfer", "athlete_label": RAW["persons"][0]["description"],
            "source_windows": [{"source_video": source, "person_id": "person_A", "event_type": "wave_catch",
                                "start": 0.0, "end": 5.8, "duration": 5.8, "score": 8}],
        }]}), encoding="utf-8")
        ledger, audit, coverage = (Path(tmp, n) for n in ("ledger.json", "audit.json", "coverage.json"))
        upstream = Path(tmp, "selector_candidate_events.json")
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        for cmd in (
            [sys.executable, "scripts/build_candidate_decision_ledger.py", str(trace), str(ledger), str(upstream)],
            [sys.executable, "scripts/build_selection_decision_audit.py", str(ledger), str(trace), str(audit)],
            [sys.executable, "scripts/build_athlete_coverage_report.py", str(ledger), str(coverage), str(audit)],
        ):
            done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
            if done.returncode != 0:
                fail(f"{cmd[1]} failed: {done.stderr[-800:]}")
        report = json.loads(coverage.read_text(encoding="utf-8"))
        rows = report.get("athletes") or report.get("clusters") or []
        person_b = [r for r in rows if "person_B" in json.dumps(r)]
        if not person_b:
            fail(f"coverage report must account for person_B, got {json.dumps(report)[:600]}")
        if not person_b[0].get("no_output_reason_explicit"):
            fail(f"person_B must end with an explicit no-output reason, got {person_b[0]}")
        rate = (report.get("summary") or {}).get("athlete_accountability_rate")
        if rate != 1.0:
            fail(f"accountability must be 1.0 when every drop is explained, got {rate}")

    print("source-window dedup accountability contract ok (duplicate athlete -> explicit duplicate_action_window)")


if __name__ == "__main__":
    main()

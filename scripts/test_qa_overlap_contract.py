#!/usr/bin/env python3
"""Reel QA of cluster N overlaps the render of cluster N+1 (QA_OVERLAP), with drafts identical to the serial loop."""
from __future__ import annotations

import os
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _fake_orchestrator(log: list, qa_seconds: float):
    """Just enough of pipeline.orchestrator for compile_clusters_with_context_qa; uploads are recorded, not sent."""
    orch = types.SimpleNamespace()
    lock = threading.Lock()

    def stamp(kind, label):
        with lock:
            log.append((kind, label, time.monotonic(), threading.current_thread().name))

    def compile_multi_source_reel(appearances, sport="", athlete_label="", _events_out=None):
        stamp("render_start", athlete_label)
        time.sleep(qa_seconds)  # rendering takes about as long as a QA check
        reel = f"/tmp/qa_overlap_{athlete_label}.mp4"
        events = [ev for app in appearances for ev in app.get("events", [])]
        if _events_out is not None:
            _events_out.append((reel, events))
        stamp("render_end", athlete_label)
        return [reel]

    def qa_gate(reels, events_out, sport, athlete_label, recompile):
        stamp("qa_start", athlete_label.split("\n")[0])
        time.sleep(qa_seconds)  # network wait on the model
        stamp("qa_end", athlete_label.split("\n")[0])
        return reels, {r: evs for r, evs in events_out}, set()

    orch.compile_multi_source_reel = compile_multi_source_reel
    orch._qa_gate = qa_gate
    orch._group_appearances = lambda evs: [{"path": "raw/x.mp4", "events": evs}]
    orch._write_status = lambda *a, **k: None
    orch._get_source_info = lambda path: {}
    orch._safe_draft_name = lambda label: "DRAFT_" + label.replace(" ", "_") + ".mp4"
    orch._record_draft_sources = lambda *a, **k: None
    uploaded: list = []
    orch.upload_draft = lambda path, name: uploaded.append(name)
    orch._save_reel_metadata = lambda *a, **k: None
    orch._MAX_UL_WORKERS = 1
    orch.config = types.SimpleNamespace(PENDING_UPLOADS_DIR="/tmp/qa_overlap_pending")
    orch.shutil = __import__("shutil")
    orch.logger = __import__("logging").getLogger("qa_overlap_test")
    orch.uploaded = uploaded
    return orch


def _clusters(n: int) -> list[dict]:
    out = []
    for i in range(n):
        src = f"raw/source_{i}.mp4"
        out.append({"description": f"athlete {i}", "appearances": [{"path": src, "events": [
            {"event_id": f"e{i}", "_src": src, "type": "surf_ride", "start": 1.0 + i, "end": 9.0 + i, "score": 8, "track_id": f"t{i}"}]}]})
    return out


def _stub_analyzer() -> None:
    """The real analyzer imports the model SDKs; the gate only swaps its qa_check_reel attribute."""
    import pipeline.stages as stages
    stub = types.ModuleType("pipeline.stages.analyzer")
    stub.qa_check_reel = lambda *a, **k: {}
    sys.modules["pipeline.stages.analyzer"] = stub
    stages.analyzer = stub


def _run(overlap: bool, n: int = 4, qa_seconds: float = 0.3):
    _stub_analyzer()
    import pipeline.context_qa_gate as cqg
    log: list = []
    orch = _fake_orchestrator(log, qa_seconds)
    # annotation helpers touch perception sidecars; identity is not under test here
    cqg._annotate_subject_gates = lambda events, source_video, label: events
    cqg._has_subject_gate_defect = lambda events: False
    os.environ["QA_OVERLAP"] = "1" if overlap else "0"
    cqg._patch_orchestrator(orch)
    started = time.monotonic()
    count = orch._compile_clusters(_clusters(n), "surfing", {})
    return count, orch.uploaded, log, time.monotonic() - started


def main() -> int:
    serial_count, serial_names, _, serial_t = _run(overlap=False)
    count, names, log, overlap_t = _run(overlap=True)

    if count != serial_count or names != serial_names:
        raise SystemExit(f"overlap must produce the same drafts in the same order: {names} vs {serial_names}")
    if names != [f"DRAFT_athlete_{i}.mp4" for i in range(4)]:
        raise SystemExit(f"drafts must follow cluster order, got {names}")

    def at(kind, label):
        return next(t for k, lab, t, _ in log if k == kind and lab == label)

    # cluster 1 renders while cluster 0 is in QA
    if not at("render_start", "athlete 1") < at("qa_end", "athlete 0"):
        raise SystemExit("cluster N+1 must render while cluster N is in QA")
    # never two QA checks at once
    qa = sorted((at("qa_start", f"athlete {i}"), at("qa_end", f"athlete {i}")) for i in range(4))
    if any(qa[i + 1][0] < qa[i][1] - 1e-3 for i in range(3)):
        raise SystemExit("at most one reel QA may run at a time")
    # QA runs off the main thread; renders stay on it
    if any(k.startswith("render") and th != "MainThread" for k, _, _, th in log):
        raise SystemExit("rendering must stay on the main thread")
    if overlap_t > serial_t * 0.8:
        raise SystemExit(f"overlap should save time: {overlap_t:.2f}s vs serial {serial_t:.2f}s")

    print(f"QA overlap contract ok (serial {serial_t:.2f}s -> overlapped {overlap_t:.2f}s, drafts identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

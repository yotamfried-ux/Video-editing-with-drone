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

    def compile_multi_source_reel(appearances, sport="", athlete_label="", _events_out=None, **kwargs):
        stamp("render_start", athlete_label)
        time.sleep(qa_seconds)  # rendering takes about as long as a QA check
        reel = f"/tmp/qa_overlap_{athlete_label}.mp4"
        events = [ev for app in appearances for ev in app.get("events", [])]
        if _events_out is not None:
            _events_out.append((reel, events))
        stamp("render_end", athlete_label)
        return [reel]

    def qa_gate(reels, events_out, sport, athlete_label, recompile, **kwargs):
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




def _assert_cross_thread_pending_scope_handoff() -> None:
    """Regression for Run #165: create_pending_scope on MainThread + activate_next_scope on reel-qa worker thread."""
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    import pipeline.publishable_pending_scope as pending_scope
    import pipeline.publishable_qa_evidence as qa_evidence
    import pipeline.publishable_reel_policy as policy
    import pipeline.silent_output_policy as silent

    policy.social_ready_issues = silent.silent_social_ready_issues
    pending_scope.install()
    with tempfile.TemporaryDirectory(prefix="sportreel-qa-overlap-scope-") as tmpdir:
        manifest = Path(tmpdir) / "publishable_reel_manifest.json"
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        policy.reset_manifest()
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reel-qa")
        futures = []
        try:
            for idx in range(3):
                label = f"Surfer athlete #{idx}"
                reel_path = str(Path(tmpdir) / f"MULTI_surfer_{idx}.mp4")
                Path(reel_path).write_bytes(b"silent")
                # MainThread creates the pending invocation scope during compile_multi_source_reel
                main_token = policy._pending_key("surfing", label)

                def _worker_qa(sport_arg: str, label_arg: str, reel_arg: str, expected_token: str) -> str:
                    activated = pending_scope.activate_next_scope(sport_arg, label_arg)
                    if activated != expected_token:
                        raise RuntimeError(f"Expected {expected_token}, got {activated}")
                    try:
                        qa_evidence.record_qa_result(
                            reel_arg,
                            {"verdict": "PASS", "engagement_score": 88, "overall": "Great surf reel", "defects": []},
                        )
                        policy.record_athlete_outcome(
                            sport=sport_arg,
                            athlete_label=label_arg,
                            final_reels=[reel_arg],
                            events_by_reel={
                                reel_arg: [
                                    {"event_id": "e1", "athlete_id": f"ath_{label_arg}", "type": "surf_ride", "start": 1.0, "end": 12.0, "score": 8, "_src": "clip.mp4"},
                                    {"event_id": "e2", "athlete_id": f"ath_{label_arg}", "type": "surf_ride", "start": 20.0, "end": 85.0, "score": 9, "_src": "clip2.mp4"},
                                ]
                            },
                            flagged_paths=set(),
                            specs_getter=lambda _p: {"has_audio": False, "duration": 96.0, "width": 1080, "height": 1920, "aspect": 1080 / 1920},
                        )
                        blocked = qa_evidence.apply_final_qa_evidence(
                            sport=sport_arg,
                            athlete_label=label_arg,
                            final_reels=[reel_arg],
                        )
                        if blocked:
                            raise RuntimeError(f"Unexpected blocked reels: {blocked}")
                        return activated
                    finally:
                        qa_evidence.clear_recorded_qa(activated)
                        pending_scope.release_scope(activated)

                futures.append(pool.submit(_worker_qa, "surfing", label, reel_path, main_token))
            for fut in futures:
                fut.result()
        finally:
            pool.shutdown(wait=True)


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

    _assert_cross_thread_pending_scope_handoff()
    print(f"QA overlap contract ok (serial {serial_t:.2f}s -> overlapped {overlap_t:.2f}s, drafts identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

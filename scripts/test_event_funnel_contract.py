#!/usr/bin/env python3
"""Contract: an athlete that ends without a reel says where and why, in the run digest.

Run 41043331384 (2cf03f76) lost 9 of 15 athlete clusters: `render_reels took 0.0s`, no reel, no log line, no reason.
`compile_multi_source_reel` returned [] silently (empty cluster, every event dropped by `_sanitize_events`, or no
partition) and `_compile_clusters` carried on. These checks pin the instrumentation that names the stage and reason:
the editor records and prints why it returned no reel, the orchestrator records each cluster's events in and reels out,
and the digest turns the records into a per-cluster verdict plus an invariant that flags any remaining silent drop.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("print_run_diagnostics", ROOT / "scripts" / "print_run_diagnostics.py")
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


def _rows(tmp: str) -> list[dict]:
    path = Path(tmp) / "pipeline-debug" / "event_funnel.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def check_editor_names_the_reason() -> None:
    import pipeline.stages.editor as editor

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TMP_DIR"] = tmp
        editor._get_duration = lambda _path: 30.0  # the source is 30 s long
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            empty = editor.compile_multi_source_reel([], athlete_label="nobody")
            no_events = editor.compile_multi_source_reel([{"path": "/x/a.mp4", "events": []}], athlete_label="empty athlete")
            dropped = editor.compile_multi_source_reel(
                [{"path": "/x/b.mp4", "events": [
                    {"start": 5.0, "end": 8.0, "score": 8, "type": "surf_ride"},     # 3 s: shorter than 4 s
                    {"start": 40.0, "end": 50.0, "score": 8, "type": "surf_ride"},   # starts after the source ends
                ]}], athlete_label="dropped athlete")
        assert empty == no_events == dropped == [], (empty, no_events, dropped)
        rows = _rows(tmp)
        reasons = {(r.get("athlete"), r["reason"]) for r in rows if r["stage"] == "compile_no_reel"}
        assert reasons == {("nobody", "no_appearances"), ("empty athlete", "cluster_has_no_events"),
                           ("dropped athlete", "all_events_dropped_by_sanitize")}, reasons
        drops = {r["reason"] for r in rows if r["stage"] == "sanitize_drop"}
        assert drops == {"shorter_than_4s_inside_source", "beyond_source_end"}, drops
        printed = out.getvalue()
        assert "No reel for 'dropped athlete': all_events_dropped_by_sanitize (events_in=2" in printed, printed


def check_orchestrator_records_every_cluster() -> None:
    """The orchestrator cannot be imported in a bare sandbox (Drive client), so check its wiring in the source."""
    tree = ast.parse((ROOT / "pipeline" / "orchestrator.py").read_text(encoding="utf-8"))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_compile_clusters")
    stages = {
        call.args[0].value
        for call in ast.walk(func)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "record"
        and isinstance(call.func.value, ast.Name) and call.func.value.id == "_event_funnel"
        and call.args and isinstance(call.args[0], ast.Constant)
    }
    assert {"cluster_input", "cluster_compiled", "cluster_after_qa"} <= stages, stages


def _digest(rows: list[dict]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        debug = Path(tmp)
        (debug / "event_funnel.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return "\n".join(diag.event_funnel(debug))


def check_digest_verdicts() -> None:
    # The shape of run 2cf03f76: 6 clusters compiled, 9 returned no reel; here 2 + 3 for brevity.
    rows = [
        {"stage": "cluster_input", "athlete": "ok athlete", "appearances": 2, "events_in": 3},
        {"stage": "cluster_compiled", "athlete": "ok athlete", "events_in": 3, "reels_out": 1},
        {"stage": "cluster_after_qa", "athlete": "ok athlete", "reels_out": 1, "flagged": 1},
        {"stage": "cluster_input", "athlete": "explained athlete", "appearances": 1, "events_in": 1},
        {"stage": "cluster_compiled", "athlete": "explained athlete", "events_in": 1, "reels_out": 0},
        {"stage": "compile_no_reel", "athlete": "explained athlete", "reason": "all_events_dropped_by_sanitize"},
        {"stage": "sanitize_drop", "source": "a.mp4", "reason": "shorter_than_4s_inside_source"},
        {"stage": "cluster_input", "athlete": "silent athlete", "appearances": 1, "events_in": 2},
        {"stage": "cluster_compiled", "athlete": "silent athlete", "events_in": 2, "reels_out": 0},
        {"stage": "person_without_usable_events", "source": "b.mp4", "person_id": "person_B", "reason": "no_complete_action"},
    ]
    text = _digest(rows)
    assert "clusters without a reel: 2/3; silent (no recorded reason): 1" in text, text
    assert "NO REEL: all_events_dropped_by_sanitize" in text, text
    assert "NO REEL: UNRECORDED (invariant violated)" in text, text
    assert "shorter_than_4s_inside_source=1" in text and "no_complete_action=1" in text, text
    assert "INVARIANT (every cluster with events ends with a reel or a recorded reason): VIOLATED for 1 cluster(s)" in text, text
    clean = _digest(rows[:3] + rows[3:6])
    assert "INVARIANT (every cluster with events ends with a reel or a recorded reason): OK" in clean, clean
    assert diag.event_funnel(Path("/nonexistent")) == ["(no event_funnel.jsonl)"]


def main() -> int:
    check_editor_names_the_reason()
    check_orchestrator_records_every_cluster()
    check_digest_verdicts()
    print("event funnel contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

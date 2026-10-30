#!/usr/bin/env python3
"""Contract: an athlete that ends without a reel says where and why, in the run digest.

Run 41043331384 (2cf03f76) lost 9 of 15 athlete clusters: `render_reels took 0.0s`, no reel, no log line, no reason.
`compile_multi_source_reel` returned [] silently (empty cluster, every event dropped by `_sanitize_events`, or no
partition) and `_compile_clusters` carried on. These checks pin the instrumentation that names the stage and reason:
the editor records and prints why it returned no reel, the orchestrator's compile wrapper records each athlete's events in and reels out,
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


def check_compile_wrapper_records_every_athlete() -> None:
    """The orchestrator cannot be imported in a bare sandbox (Drive client, langsmith), so check its wiring in the source.

    Run 2cf03f76/e79da66e showed why the record must sit in the module-level compile wrapper: `_compile_clusters` is
    replaced at runtime by the context-QA gate, so anything recorded inside it never ran."""
    tree = ast.parse((ROOT / "pipeline" / "orchestrator.py").read_text(encoding="utf-8"))
    wrapper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "compile_multi_source_reel")
    calls = {
        call.func.attr
        for call in ast.walk(wrapper)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name) and call.func.value.id == "_event_funnel"
    }
    assert "record_compile" in calls, calls

    from integrations import event_funnel

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TMP_DIR"] = tmp
        event_funnel.record_compile("athlete A", [{"path": "/x/a.mp4", "events": [{}, {}]}, {"path": "/x/b.mp4", "events": [{}]}], ["r.mp4"])
        event_funnel.record_compile("athlete B", None, [])
        rows = _rows(tmp)
        assert [(r["athlete"], r["appearances"], r["events_in"], r["reels_out"]) for r in rows] == [
            ("athlete A", 2, 3, 1), ("athlete B", 0, 0, 0)], rows
        assert rows[0]["sources"] == ["a.mp4", "b.mp4"], rows[0]


def _digest(rows: list[dict]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        debug = Path(tmp)
        (debug / "event_funnel.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return "\n".join(diag.event_funnel(debug))


def check_digest_verdicts() -> None:
    # The shape of the real runs: some athletes compile, some return no reel with a recorded reason, one silently.
    rows = [
        {"stage": "cluster_compiled", "athlete": "ok athlete", "appearances": 2, "events_in": 3, "reels_out": 1},
        {"stage": "cluster_compiled", "athlete": "reedit athlete", "appearances": 1, "events_in": 2, "reels_out": 0},
        {"stage": "cluster_compiled", "athlete": "reedit athlete", "appearances": 1, "events_in": 2, "reels_out": 1},
        {"stage": "compile_no_reel", "athlete": "explained athlete", "reason": "all_events_dropped_by_sanitize"},
        {"stage": "cluster_compiled", "athlete": "explained athlete", "appearances": 1, "events_in": 1, "reels_out": 0},
        {"stage": "sanitize_drop", "source": "a.mp4", "reason": "shorter_than_4s_inside_source",
         "start": 26.5, "end": 29.0, "source_duration": 29.0},
        {"stage": "cluster_compiled", "athlete": "silent athlete", "appearances": 1, "events_in": 2, "reels_out": 0},
        {"stage": "person_without_usable_events", "source": "b.mp4", "person_id": "person_B", "reason": "no_complete_action"},
    ]
    text = _digest(rows)
    assert "athletes that entered compile: 4" in text, text
    assert "athletes without a reel: 2/4; silent (no recorded reason): 1" in text, text
    assert "NO REEL: all_events_dropped_by_sanitize" in text, text
    assert "NO REEL: UNRECORDED (invariant violated)" in text, text
    reedit_line = next(line for line in text.splitlines() if line.strip().startswith("reedit athlete"))
    assert reedit_line.rstrip().endswith("ok"), reedit_line  # the last compile decides, not the first
    assert "a.mp4" in text and "26.5-29.0" in text and "29.0" in text and "shorter_than_4s_inside_source=1" in text, text
    assert "no_complete_action=1" in text, text
    assert "VIOLATED for 1 athlete(s)" in text, text
    clean = _digest(rows[:6])
    assert "(every athlete with events ends with a reel or a recorded reason): OK" in clean, clean
    # No compile rows at all must never read as a pass (the first version of this check did exactly that).
    empty = _digest([r for r in rows if r["stage"] != "cluster_compiled"])
    assert "NOT EVALUATED" in empty and ": OK" not in empty.split("INVARIANT")[-1], empty
    assert diag.event_funnel(Path("/nonexistent")) == ["(no event_funnel.jsonl)"]


def main() -> int:
    check_editor_names_the_reason()
    check_compile_wrapper_records_every_athlete()
    check_digest_verdicts()
    print("event funnel contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

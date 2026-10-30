#!/usr/bin/env python3
"""Contract: a QA re-edit that cannot change the render is skipped instead of re-rendered and re-graded.

Real run 39726001357: 5 of 10 re-edit renders had the same duration and size as the render before
(PREMATURE_CUT asked for +3s on clips already running to the end of their source), each costing a
render of 75-215s plus a QA call, and the one reel that turned PASS did so on an identical render.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DURATIONS = {"short.mp4": 10.14, "long.mp4": 40.0, "tiny.mp4": 6.32}


def _duration(path: str) -> float:
    return DURATIONS[path]


def _rendered(src: str, start: float, end: float, **extra) -> dict:
    """An event as the editor persists it after rendering (final_cut_* = the rendered window)."""
    return {"_src": src, "type": "wave_catch", "start": start, "end": end, "description": "x",
            "final_cut_start": min(start, DURATIONS[src]), "final_cut_end": min(end, DURATIONS[src]),
            "edit": {"slowmo": False, "zoom": 1.2}, **extra}


def _premature_cut_fix(before: list[dict]) -> list[dict]:
    """What orchestrator._apply_qa_fixes + the re-edit window contract produce for PREMATURE_CUT."""
    from pipeline.qa_reedit_window_contract import mark_reedit_extensions
    fixed = [dict(e) for e in before]
    for e in fixed:
        e["end"] = float(e["end"]) + 3.0
    return mark_reedit_extensions(before, fixed, [{"type": "PREMATURE_CUT", "severity": "critical"}])


def test_extension_past_the_end_of_the_source_is_a_noop() -> None:
    from pipeline.qa_reedit_noop import reedit_is_noop
    # run case 0097: the window was already padded past the 10.14s source -> rendered to its end
    before = [_rendered("short.mp4", 1.0, 12.0)]
    noop, why = reedit_is_noop(before, _premature_cut_fix(before), _duration)
    assert noop and "source ends at 10.1s" in why, (noop, why)
    # run case 0095: 6.3s source
    before = [_rendered("tiny.mp4", 0.0, 7.5)]
    assert reedit_is_noop(before, _premature_cut_fix(before), _duration)[0]


def test_real_changes_are_not_noops() -> None:
    from pipeline.qa_reedit_noop import reedit_is_noop
    # room left in the source: the +3s extension really changes the render
    before = [_rendered("long.mp4", 5.0, 14.0)]
    assert not reedit_is_noop(before, _premature_cut_fix(before), _duration)[0]
    # dropping a clip
    two = [_rendered("long.mp4", 5.0, 14.0), _rendered("short.mp4", 0.0, 9.0)]
    assert not reedit_is_noop(two, two[:1], _duration)[0]
    # slow-motion switched off
    slowmo = [_rendered("long.mp4", 5.0, 14.0)]
    slowmo[0]["edit"] = {"slowmo": True, "zoom": 1.2}
    off = [{**slowmo[0], "edit": {"slowmo": False, "zoom": 1.2}}]
    assert not reedit_is_noop(slowmo, off, _duration)[0]
    # slow-motion already off: UNNATURAL_SLOWMO fix changes nothing
    same = [dict(e) for e in off]
    assert reedit_is_noop(off, same, _duration)[0]
    # the cold-open teaser is ignored on both sides
    with_teaser = [{"_teaser": True, "_src": "long.mp4", "start": 0, "end": 3}, *off]
    assert reedit_is_noop(with_teaser, same, _duration)[0]


def test_unknown_inputs_fail_open_to_the_old_behaviour() -> None:
    from pipeline.qa_reedit_noop import reedit_is_noop

    def broken(_path):
        raise OSError("ffprobe failed")

    before = [_rendered("short.mp4", 1.0, 12.0)]
    assert reedit_is_noop(before, _premature_cut_fix(before), broken) == (False, "")
    assert reedit_is_noop([], [], _duration) == (False, "")
    assert reedit_is_noop(before, [], _duration) == (False, "")
    no_src = [{"type": "wave_catch", "start": 1.0, "end": 12.0}]
    assert reedit_is_noop(no_src, [dict(no_src[0], end=15.0)], _duration)[0] is False, "unsourced events with a longer end differ"
    os.environ["QA_SKIP_NOOP_REEDIT"] = "0"
    try:
        from pipeline import qa_reedit_noop
        assert not qa_reedit_noop.enabled()
    finally:
        os.environ.pop("QA_SKIP_NOOP_REEDIT", None)


def _import_orchestrator():
    class _Config(types.SimpleNamespace):
        def __getattr__(self, name):          # module-level settings the orchestrator reads at import
            if name.isupper():
                return 1
            raise AttributeError(name)

    cfg = _Config(QA_REEL_CHECK=True, QA_GATE=True, QA_MAX_RETRIES=2, TMP_DIR="/tmp", MIN_EVENT_SEC=5)
    stubs = {
        "config": cfg,
        "integrations.drive": types.SimpleNamespace(**{n: (lambda *a, **k: None) for n in (
            "download_video", "get_new_videos", "mark_as_processed", "flag_quality_issue", "upload_draft", "record_failure")}),
        "integrations.run_status": types.SimpleNamespace(mark_run=lambda *a, **k: None),
        "pipeline.stages.analyzer": types.SimpleNamespace(analyze_session=lambda *a, **k: None, qa_check_reel=None),
        "pipeline.stages.editor": types.SimpleNamespace(create_reel=None, compile_multi_source_reel=None, drain_quality_issues=lambda: []),
        "pipeline.stages.identity": types.SimpleNamespace(cluster_clips=None),
        "pipeline.stages.feedback": types.SimpleNamespace(get_stats=lambda *a, **k: {}),
        "integrations.ffmpeg": types.SimpleNamespace(get_source_info=lambda *a, **k: {}, get_duration=_duration),
    }
    sys.modules.update(stubs)
    import importlib
    return importlib.import_module("pipeline.orchestrator"), cfg


def test_the_qa_loop_skips_the_rerender_and_still_flags_the_reel() -> None:
    orch, _cfg = _import_orchestrator()
    orch._write_status = lambda *a, **k: None
    qa_calls: list[str] = []
    recompiles: list[int] = []
    fail = {"verdict": "FAIL", "engagement_score": 45, "overall": "x",
            "defects": [{"type": "PREMATURE_CUT", "severity": "critical", "at_seconds": 3, "note": "cut early"}]}

    analyzer = sys.modules["pipeline.stages.analyzer"]
    analyzer.qa_check_reel = lambda reel, **k: qa_calls.append(reel) or dict(fail)
    # the exact situation of the 10.14s source whose padded window already reached its end
    events = [_rendered("short.mp4", 1.0, 12.0)]
    orch._event_index_for_qa_defect = lambda evs, d: 0
    reels = ["/tmp/reel_a.mp4"]
    out, _by, flagged = orch._qa_gate(reels, [("/tmp/reel_a.mp4", events)], "surfing", "athlete",
                                      lambda fixed, new_out: recompiles.append(1) or ["/tmp/never.mp4"])
    assert recompiles == [], "a no-op repair must not be re-rendered"
    assert qa_calls == ["/tmp/reel_a.mp4"], "and must not be re-graded"
    assert out == reels and flagged == {"/tmp/reel_a.mp4"}, "the failing reel is still flagged for the operator"

    # same defect on a source with room to extend: the old behaviour (re-render + re-check) stays
    qa_calls.clear()
    recompiles.clear()
    long_events = [_rendered("long.mp4", 5.0, 14.0)]
    orch._qa_gate(["/tmp/reel_b.mp4"], [("/tmp/reel_b.mp4", long_events)], "surfing", "athlete",
                  lambda fixed, new_out: recompiles.append(1) or (new_out.append(("/tmp/reel_b2.mp4", fixed)) or ["/tmp/reel_b2.mp4"]))
    assert len(recompiles) == 2 and len(qa_calls) == 3, (len(recompiles), len(qa_calls))


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print("QA re-edit no-op contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

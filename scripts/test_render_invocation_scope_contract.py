#!/usr/bin/env python3
"""Regression for run 42474968394: "RuntimeError: unknown render invocation_id: inv_0_...".

The real bootstrap patch stack wraps the editor entry points many times. The outermost wrapper
(teaser_policy_runtime) did not accept **kwargs, so ``compile_multi_source_reel(..., invocation_id=...)``
raised TypeError, context_qa_gate silently re-rendered WITHOUT the ID, and the QA worker then tried to
activate a scope that was never registered. This test drives the REAL install order over a fake
innermost editor and requires the explicit ID to survive render -> QA activation, with exactly one render.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPORTREEL_REQUIRE_EXPLICIT_SCOPE", "1")


def main() -> None:
    import pipeline.stages.editor as editor

    renders: list[dict] = []

    def fake_compile(appearances, sport="", athlete_label="", _events_out=None, **kwargs):
        renders.append({"kind": "multi", "label": athlete_label, "kwargs": dict(kwargs)})
        reel = f"/tmp/invocation_scope_{len(renders)}.mp4"
        if _events_out is not None:
            _events_out.append((reel, [dict(e) for app in appearances or [] for e in app.get("events", [])]))
        return [reel]

    def fake_create(video_path, events, sport="", athlete_label="", _events_out=None, **kwargs):
        renders.append({"kind": "single", "label": athlete_label, "kwargs": dict(kwargs)})
        reel = f"/tmp/invocation_scope_{len(renders)}.mp4"
        if _events_out is not None:
            _events_out.append((reel, [dict(e) for e in events or []]))
        return [reel]

    editor.compile_multi_source_reel = fake_compile
    editor.create_reel = fake_create
    editor._get_duration = lambda path: 60.0

    from pipeline import bootstrap

    bootstrap.install_pre_orchestrator_patches()

    import pipeline.publishable_pending_scope as pending_scope
    import pipeline.publishable_reel_policy as policy

    # Variant canonicalization probes real media files; it is not what this contract is about.
    policy.canonicalize_publishable_variants = lambda reels, events_out, **_: (list(reels), list(events_out), [])

    if editor.compile_multi_source_reel is fake_compile:
        raise SystemExit("bootstrap did not wrap compile_multi_source_reel; the contract would be vacuous")

    for kind, label, inv_id in (
        ("multi", "Surfer in red shorts", "inv_0_regress"),
        ("single", "Surfer in blue top", "inv_1_regress"),
    ):
        events = [{"event_id": f"e_{inv_id}", "type": "surf_ride", "start": 2.0, "end": 12.0, "score": 8,
                   "track_id": "7", "_src": "raw/a.mp4"}]
        out: list = []
        before = len(renders)
        if kind == "multi":
            editor.compile_multi_source_reel(
                [{"path": "raw/a.mp4", "events": events}],
                sport="surfing", athlete_label=label, _events_out=out, invocation_id=inv_id,
            )
        else:
            editor.create_reel("raw/a.mp4", events, sport="surfing", athlete_label=label,
                               _events_out=out, invocation_id=inv_id)
        if len(renders) - before != 1:
            raise SystemExit(f"{kind}: expected exactly one render, got {len(renders) - before}")
        stamped = {ev.get("_render_invocation_id") for _reel, evs in out for ev in evs}
        if stamped != {inv_id}:
            raise SystemExit(f"{kind}: events must carry the explicit invocation_id {inv_id!r}, got {stamped!r}")
        token = pending_scope.activate_next_scope("surfing", label, invocation_id=inv_id)
        if not token:
            raise SystemExit(f"{kind}: QA could not activate the render scope for {inv_id!r}")
        pending_scope.release_scope(token)

    print("render invocation scope contract ok (explicit IDs survive the full bootstrap wrapper stack)")


if __name__ == "__main__":
    main()

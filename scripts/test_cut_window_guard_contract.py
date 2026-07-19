#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.cut_window_guard import apply_cut_window_guard, apply_to_appearances, needs_cut_window_guard
    from pipeline.draft_diagnostics import build_diagnostic_artifact
    from pipeline.window_policy import resolve_window

    ev = {"event_id": "w1", "type": "cutback", "start": 10, "end": 17, "score": 8, "description": "surfer on wave"}
    guarded = apply_cut_window_guard(ev, 40, "surfing")
    if guarded.get("outcome_end") != 20:
        raise SystemExit("missing outcome evidence should extend tail")
    if guarded.get("cut_window_evidence_status") != "inferred_tail_padding":
        raise SystemExit("cut window evidence status missing")

    resolved = resolve_window(guarded, 40)
    if not resolved or resolved.get("final_cut_end") < 20:
        raise SystemExit("window policy did not preserve inferred outcome")
    if "outcome" not in resolved.get("cut_adjustment_reason", ""):
        raise SystemExit("window adjustment reason should include outcome")

    with_outcome = {"type": "cutback", "start": 10, "end": 17, "outcome_end": 18}
    if needs_cut_window_guard(with_outcome, "surfing"):
        raise SystemExit("events with outcome evidence must not be guarded")

    teaser = {"type": "cutback", "start": 10, "end": 17, "_teaser": True}
    if needs_cut_window_guard(teaser, "surfing"):
        raise SystemExit("teaser must not be guarded")

    non_sport = {"type": "highlight", "start": 1, "end": 5}
    if apply_cut_window_guard(non_sport, 30, "football") != non_sport:
        raise SystemExit("non matching sport should not change")

    apps = [{"path": "clip_a.mp4", "events": [ev]}]
    guarded_apps = apply_to_appearances(apps, "surfing", lambda _path: 40)
    if guarded_apps[0]["events"][0].get("outcome_end") != 20:
        raise SystemExit("appearances must be guarded before metadata capture")

    artifact = build_diagnostic_artifact("DRAFT_cut.mp4", "surfing", guarded_apps[0]["events"], {}, "review/DRAFT_cut.mp4")
    cut_meta = artifact["ordered_events"][0].get("cut_window_guard") or {}
    if cut_meta.get("status") != "inferred_tail_padding" or cut_meta.get("window_uncertain") is not True:
        raise SystemExit("diagnostic artifact missing cut window guard metadata")

    text = (ROOT / "pipeline/cut_window_guard.py").read_text(encoding="utf-8")
    diag = (ROOT / "pipeline/draft_diagnostics.py").read_text(encoding="utf-8")
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    audit = (ROOT / "docs/pipeline-quality-audit-real-run-20260705.md").read_text(encoding="utf-8")
    for token in ["apply_cut_window_guard", "apply_to_appearances", "compile_guarded", "cut_clip_guarded"]:
        if token not in text:
            raise SystemExit(f"missing token: {token}")
    if "cut_window_guard" not in diag:
        raise SystemExit("diagnostics must include cut window guard metadata")
    if "pipeline.cut_window_guard" not in boot:
        raise SystemExit("cut window guard is not bootstrapped")
    if "REAL-CUT-001" not in audit:
        raise SystemExit("audit missing REAL-CUT-001")

    print("Cut window guard contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

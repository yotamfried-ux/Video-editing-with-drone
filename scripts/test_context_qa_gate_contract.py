#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def ev(event_id, source, start, end, score=8, **extra):
    return {"event_id": event_id, "_src": source, "type": "cutback", "start": start, "end": end, "score": score, **extra}


def main() -> int:
    from pipeline.context_qa_gate import build_qa_package, draft_fingerprint, filter_duplicate_draft_candidates
    from pipeline.context_qa_long_video import _stage_reel_candidate
    from pipeline.draft_diagnostics import build_diagnostic_artifact

    first_events = [ev("gemini_person_a_event_1", "raw/source.mp4", 10.0, 18.0, 7, track_id="t1")]
    second_events = [ev("different_description_event_9", "raw/source.mp4", 10.1, 18.1, 9, track_id="t1")]
    if draft_fingerprint(first_events) != draft_fingerprint(second_events):
        raise SystemExit("same source/time draft must fingerprint the same even with different event ids")

    pending = [("/tmp/reel_a.mp4", "DRAFT_black_one_piece.mp4"), ("/tmp/reel_b.mp4", "DRAFT_brown_bikini.mp4")]
    meta = [(pending[0][0], pending[0][1], first_events, {}), (pending[1][0], pending[1][1], second_events, {})]
    filtered_pending, filtered_meta, dropped = filter_duplicate_draft_candidates(pending, meta)
    if len(filtered_pending) != 1 or filtered_pending[0][1] != "DRAFT_brown_bikini.mp4":
        raise SystemExit("run-level QA must keep only the better duplicate draft")
    if not dropped or dropped[0].get("defect_type") != "DUPLICATE_DRAFT":
        raise SystemExit("duplicate draft must emit DUPLICATE_DRAFT evidence")
    kept_events = filtered_meta[0][2]
    if kept_events[0].get("dedup_dropped_duplicates", [])[0].get("dropped_draft") != "DRAFT_black_one_piece.mp4":
        raise SystemExit("kept draft must preserve dropped duplicate evidence")

    package = build_qa_package(filtered_pending[0][0], filtered_pending[0][1], kept_events, {})
    if not package.get("source_windows") or package["source_windows"][0]["source"] != "raw/source.mp4":
        raise SystemExit("QA package must expose source windows")

    artifact = build_diagnostic_artifact(filtered_pending[0][1], "surfing", kept_events, {}, "review/DRAFT_brown_bikini.mp4")
    if not artifact["dropped_events"] or artifact["dropped_events"][0].get("detail", {}).get("defect_type") != "DUPLICATE_DRAFT":
        raise SystemExit("diagnostic artifact must preserve duplicate draft evidence")

    distinct_pending = [("/tmp/reel_c.mp4", "DRAFT_1.mp4"), ("/tmp/reel_d.mp4", "DRAFT_2.mp4")]
    distinct_meta = [(distinct_pending[0][0], distinct_pending[0][1], [ev("a", "raw/source.mp4", 1, 7)], {}), (distinct_pending[1][0], distinct_pending[1][1], [ev("b", "raw/source.mp4", 20, 27)], {})]
    out_pending, _, out_dropped = filter_duplicate_draft_candidates(distinct_pending, distinct_meta)
    if len(out_pending) != 2 or out_dropped:
        raise SystemExit("distinct source windows must not be dropped")

    with tempfile.TemporaryDirectory() as tmp:
        reel = Path(tmp) / "REEL_same_source_surfing.mp4"
        reel.write_bytes(b"first-render")
        first_stage = _stage_reel_candidate(str(reel), tmp, 0, "DRAFT_first.mp4")
        reel.write_bytes(b"second-render")
        second_stage = _stage_reel_candidate(str(reel), tmp, 1, "DRAFT_second.mp4")
        if not first_stage or not second_stage:
            raise SystemExit("long-video staging must return staged paths for existing renders")
        if first_stage == second_stage:
            raise SystemExit("long-video staging must create unique paths per candidate")
        if Path(first_stage).read_bytes() != b"first-render":
            raise SystemExit("first staged candidate must preserve the first render before overwrite")
        if Path(second_stage).read_bytes() != b"second-render":
            raise SystemExit("second staged candidate must preserve the second render")

    text = (ROOT / "pipeline/context_qa_gate.py").read_text(encoding="utf-8")
    long_video = (ROOT / "pipeline/context_qa_long_video.py").read_text(encoding="utf-8")
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    audit = (ROOT / "docs/pipeline-context-qa-audit-20260705.md").read_text(encoding="utf-8")
    for token in ["build_qa_package", "filter_duplicate_draft_candidates", "DUPLICATE_DRAFT", "compile_clusters_with_context_qa"]:
        if token not in text:
            raise SystemExit(f"missing context QA token: {token}")
    for token in ["_stage_reel_candidate", "draft-candidate", "produced_reels", "staged_reels"]:
        if token not in long_video:
            raise SystemExit(f"missing long-video staging token: {token}")
    if "pipeline.context_qa_gate" not in boot:
        raise SystemExit("context QA gate is not bootstrapped")
    if "REAL-QA-001" not in audit or "REAL-DUP-002" not in audit or "REAL-UPLOAD-003" not in audit:
        raise SystemExit("context QA audit missing required gaps")

    print("Context QA gate contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

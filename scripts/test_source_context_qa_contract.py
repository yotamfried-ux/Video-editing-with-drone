#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.context_qa_gate import build_edit_context, _context_prompt

    event = {"event_id": "ev1", "_src": "raw/source.mp4", "start": 10, "end": 18, "final_cut_end": 21, "track_id": "t1", "identity_gate": {"decision": "pass"}, "cut_window_evidence_status": "inferred_tail_padding", "dedup_dropped_duplicates": [{"defect_type": "DUPLICATE_DRAFT"}]}
    ctx = build_edit_context("/tmp/reel.mp4", [event, {"_teaser": True}])
    if len(ctx["source_windows"]) != 1:
        raise SystemExit("bad source window count")
    prompt = _context_prompt(ctx)
    for token in ["EDIT_SOURCE_CONTEXT_JSON", "raw/source.mp4", "identity_gate", "inferred_tail_padding", "DUPLICATE_DRAFT"]:
        if token not in prompt:
            raise SystemExit(f"missing token: {token}")
    text = (ROOT / "pipeline/context_qa_gate.py").read_text(encoding="utf-8")
    for token in ["build_edit_context", "_context_prompt", "_qa_gate_with_edit_context"]:
        if token not in text:
            raise SystemExit(f"missing implementation token: {token}")
    print("Source context QA contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

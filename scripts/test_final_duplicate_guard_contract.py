#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def e(event_id, source, start, end, score=8, **extra):
    return {"event_id": event_id, "_src": source, "type": "cutback", "start": start, "end": end, "score": score, **extra}


def main() -> int:
    from pipeline.draft_diagnostics import build_diagnostic_artifact
    from pipeline.final_duplicate_guard import remove_duplicate_events

    out = remove_duplicate_events([e("a", "cam_a.mp4", 10, 18, 7), e("a", "cam_a.mp4", 10.2, 18.2, 9)])
    if len(out) != 1 or out[0]["score"] != 9:
        raise SystemExit("same event id did not keep best event")
    if out[0].get("dedup_dropped_duplicates", [{}])[0].get("defect_type") != "DUPLICATE_MOMENT":
        raise SystemExit("missing duplicate diagnostic")

    out = remove_duplicate_events([e("a1", "cam_a.mp4", 20, 30, 9), e("a2", "cam_a.mp4", 21, 29, 7)])
    if len(out) != 1 or out[0].get("dedup_dropped_duplicates", [{}])[0].get("reason") != "same_source_time_overlap":
        raise SystemExit("same-source overlap was not removed")

    out = remove_duplicate_events([e("f1", "cam_a.mp4", 0, 8, 7, event_fingerprint="wave1"), e("f2", "cam_b.mp4", 45, 53, 8, event_fingerprint="wave1")])
    if len(out) != 1 or out[0]["event_id"] != "f2":
        raise SystemExit("fingerprint duplicate did not keep best event")

    out = remove_duplicate_events([e("c", "cam_a.mp4", 10, 20, 9), e("c_teaser", "cam_a.mp4", 14, 16.5, 9, _teaser=True)])
    if len(out) != 2:
        raise SystemExit("teaser duplicate should remain")

    out = remove_duplicate_events([e("d1", "cam_a.mp4", 0, 8, 8), e("d2", "cam_a.mp4", 12, 20, 8)])
    if len(out) != 2:
        raise SystemExit("distinct events were removed")

    artifact = build_diagnostic_artifact("DRAFT_dup.mp4", "surfing", remove_duplicate_events([e("x1", "cam_a.mp4", 20, 30, 9), e("x2", "cam_a.mp4", 21, 29, 7)]), {}, "review/DRAFT_dup.mp4")
    if not artifact["dropped_events"]:
        raise SystemExit("duplicate drop was not persisted to artifact")

    text = (ROOT / "pipeline/final_duplicate_guard.py").read_text(encoding="utf-8")
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    audit = (ROOT / "docs/pipeline-quality-audit-real-run-20260705.md").read_text(encoding="utf-8")
    for token in ["remove_duplicate_events", "_duplicate_reason", "DUPLICATE_MOMENT", "_patch_editor"]:
        if token not in text:
            raise SystemExit(f"missing token: {token}")
    if "pipeline.final_duplicate_guard" not in boot:
        raise SystemExit("guard not bootstrapped")
    if "REAL-DUP-001" not in audit:
        raise SystemExit("audit missing REAL-DUP-001")

    print("Final duplicate guard contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

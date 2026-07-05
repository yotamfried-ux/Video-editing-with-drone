#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.source_evidence_runner import _context_defects

    context = {"source_windows": [{"duplicate_evidence": [{"defect_type": "RIDE_BOUNDARY_UNCERTAIN", "severity": "critical"}, {"defect_type": "IDENTITY_UNCERTAIN", "severity": "critical"}]}]}
    defects = _context_defects(context)
    types = {d.get("type") for d in defects}
    if {"RIDE_BOUNDARY_UNCERTAIN", "IDENTITY_UNCERTAIN"} - types:
        raise SystemExit("ride defects must be blocking QA context defects")

    text = (ROOT / "pipeline/source_evidence_runner.py").read_text(encoding="utf-8")
    for token in ["BLOCKING_CONTEXT_TYPES", "RIDE_BOUNDARY_UNCERTAIN", "IDENTITY_UNCERTAIN", "qa_review_required"]:
        if token not in text:
            raise SystemExit(f"missing token: {token}")

    print("Surf ride QA contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

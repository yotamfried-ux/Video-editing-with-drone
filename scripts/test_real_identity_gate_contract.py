#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def app(path: str, event_id: str, track_id=None):
    event = {"event_id": event_id, "type": "cutback", "score": 8, "start": 1, "end": 8}
    if track_id is not None:
        event["track_id"] = track_id
    return {"path": path, "events": [event]}


def main() -> int:
    from pipeline.real_identity_gate import enforce_identity_gate

    stable = [{"description": "same surfer", "appearances": [app("a.mp4", "a1", "t7"), app("b.mp4", "b1", "t7")]}]
    out = enforce_identity_gate(stable)
    if len(out) != 1 or out[0].get("_identity_gate") != "pass":
        raise SystemExit("stable track cluster should pass")
    if out[0]["appearances"][0]["events"][0].get("identity_gate", {}).get("stable_track_id") != "t7":
        raise SystemExit("stable track evidence was not persisted")

    conflicting = [{"description": "mixed surfer", "appearances": [app("a.mp4", "a1", "t1"), app("b.mp4", "b1", "t2")]}]
    out = enforce_identity_gate(conflicting)
    if len(out) != 2 or any(len(c.get("appearances", [])) != 1 for c in out):
        raise SystemExit("conflicting tracks must split to single appearances")
    if not all(c.get("_identity_gate_reason") == "conflicting_track_ids" for c in out):
        raise SystemExit("conflicting track split reason missing")
    first_gate = out[0]["appearances"][0]["events"][0].get("identity_gate", {})
    if first_gate.get("decision") != "split_to_single_appearance" or first_gate.get("appearance", {}).get("track_ids") != ["t1"]:
        raise SystemExit("split diagnostics missing event/source/track details")

    missing = [{"description": "uncertain surfer", "appearances": [app("a.mp4", "a1"), app("b.mp4", "b1")]}]
    out = enforce_identity_gate(missing)
    if len(out) != 2 or not all(c.get("_identity_gate_reason") == "missing_track_evidence" for c in out):
        raise SystemExit("missing evidence multi-appearance cluster must split")

    single = [{"description": "single surfer", "appearances": [app("a.mp4", "a1")]}]
    out = enforce_identity_gate(single)
    if len(out) != 1 or out[0]["description"] != "single surfer":
        raise SystemExit("single appearance should pass without cross-event identity proof")

    text = (ROOT / "pipeline/real_identity_gate.py").read_text(encoding="utf-8")
    boot = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    audit = (ROOT / "docs/pipeline-quality-audit-real-run-20260705.md").read_text(encoding="utf-8")
    for token in ["enforce_identity_gate", "_wrap_existing_hook", "_patch_orchestrator"]:
        if token not in text:
            raise SystemExit(f"missing identity gate token: {token}")
    if "MetaPathFinder" in text or "importlib.abc" in text:
        raise SystemExit("real identity gate must compose with QA hook, not install a competing import hook")
    if "from pipeline.real_identity_gate import install" not in boot:
        raise SystemExit("real identity gate is not bootstrapped")
    if "REAL-ID-001" not in audit or "Google Cloud Video Intelligence object tracking" not in audit:
        raise SystemExit("real-run audit addendum missing REAL-ID-001 or official references")

    print("Real identity gate contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

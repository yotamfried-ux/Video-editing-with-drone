#!/usr/bin/env python3
"""One reel per athlete: visually verified multi-source clusters stay together; everything else still splits."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def app(path, event_id, *track_ids):
    events = [{"event_id": f"{event_id}{i}", "type": "ride", "score": 8, "start": 1, "end": 8,
               **({"track_id": t} if t is not None else {})} for i, t in enumerate(track_ids or (None,))]
    return {"path": path, "events": events}


def cluster(*apps, verified=False):
    item = {"description": "man in black top", "appearances": list(apps)}
    if verified:
        item["_visual_verified"] = True
    return item


def test_verified_cluster_with_one_track_per_source_stays_one_reel() -> None:
    from pipeline.real_identity_gate import enforce_identity_gate
    out = enforce_identity_gate([cluster(app("a.mp4", "a", "t1"), app("b.mp4", "b", "t9"), app("c.mp4", "c", None), verified=True)])
    assert len(out) == 1 and len(out[0]["appearances"]) == 3, out
    assert out[0]["_identity_gate"] == "pass"
    assert out[0]["_identity_gate_reason"] == "visual_verified_per_source_tracks"
    gate = out[0]["appearances"][0]["events"][0]["identity_gate"]
    assert gate["decision"] == "pass" and gate["reason"] == "visual_verified_per_source_tracks", gate


def test_unverified_cluster_still_splits() -> None:
    from pipeline.real_identity_gate import enforce_identity_gate
    out = enforce_identity_gate([cluster(app("a.mp4", "a", "t1"), app("b.mp4", "b", "t9"))])
    assert len(out) == 2 and all(len(c["appearances"]) == 1 for c in out), out


def test_two_tracks_inside_one_source_still_split() -> None:
    from pipeline.real_identity_gate import enforce_identity_gate
    out = enforce_identity_gate([cluster(app("a.mp4", "a", "t1", "t2"), app("b.mp4", "b", "t9"), verified=True)])
    assert len(out) == 2, out


def test_kill_switch_restores_split() -> None:
    from pipeline.real_identity_gate import enforce_identity_gate
    os.environ["SPORTREEL_MERGE_VERIFIED_CLUSTERS"] = "0"
    try:
        out = enforce_identity_gate([cluster(app("a.mp4", "a", "t1"), app("b.mp4", "b", "t9"), verified=True)])
    finally:
        os.environ.pop("SPORTREEL_MERGE_VERIFIED_CLUSTERS", None)
    assert len(out) == 2, out


def test_strip_internal_fields_keeps_only_the_verified_marker() -> None:
    from pipeline.stages.identity import _strip_internal_fields
    out = _strip_internal_fields([{**cluster(app("a.mp4", "a"), verified=True), "_secret": 1}])
    assert out[0].get("_visual_verified") is True and "_secret" not in out[0], out
    assert "_visual_verified" not in _strip_internal_fields([cluster(app("a.mp4", "a"))])[0]


def test_verifier_marks_only_positively_confirmed_clusters() -> None:
    import types
    import pipeline.identity_failsafe as failsafe
    import pipeline.stages.identity as identity
    thumb = ROOT / "scripts" / "test_verified_cluster_merge_contract.py"  # any existing file
    apps = [{"path": "a.mp4", "thumbnail": str(thumb), "events": []}, {"path": "b.mp4", "thumbnail": str(thumb), "events": []}]

    def run(answer: str):
        fake_model = types.SimpleNamespace(generate_content=lambda *a, **k: types.SimpleNamespace(text=answer))
        fake_genai = types.SimpleNamespace(
            upload_file=lambda **k: types.SimpleNamespace(name="f"), delete_file=lambda n: None,
            GenerativeModel=lambda model_name=None: fake_model)
        saved = (identity.genai, identity._retry_gemini)
        identity.genai, identity._retry_gemini = fake_genai, lambda fn, *a, **k: fn()
        try:
            return failsafe._wrap_verify_multi_clusters(identity)([{"description": "x", "appearances": list(apps)}])
        finally:
            identity.genai, identity._retry_gemini = saved

    same = run('{"same_person": true, "mismatched_indices": []}')
    assert len(same) == 1 and same[0].get("_visual_verified") is True, same
    different = run('{"same_person": false, "mismatched_indices": []}')
    assert len(different) == 2 and not any(c.get("_visual_verified") for c in different), different


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS verified cluster merge contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

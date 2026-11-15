#!/usr/bin/env python3
"""Root-cause fixes from the deep verification of 2026-11-15 (PR #387), one assertion per confirmed mechanism.

M2  A cluster is "_visual_verified" only when the image verifier confirmed it. Agreement between text
    descriptions does not set it, and a text merge clears an earlier confirmation.
    Run 43710581656: 0143 + 0152 passed the identity gate as "visual_verified_per_source_tracks" although the
    verifier was never shown an image of the pair.
M2  A multi-source cluster the gate keeps together without confirmation is not publishable.
M4  Every event gets a canonical id when it is created; a later window change does not change it.
M5  A run closes only the reprocess requests it consumed, each by its own result. Nothing is closed globally.
M1  Admission is a typed verdict that names what it rests on.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def app(path: str, description: str, track: int) -> dict:
    return {"path": path, "_clip_index": path, "_person_id": "person_A", "description": description,
            "_description": description, "events": [{"start": 1.0, "end": 8.0, "track_id": track}]}


def main() -> int:
    from pipeline.stages import identity

    # ---- M2: text agreement is not visual verification
    a_desc = "surfer on a pink surfboard, wearing a light-colored top and dark shorts"   # 0143, run 43710581656
    b_desc = "surfer on a pink surfboard with a white top and dark shorts"               # 0152
    same = "Man in a white long-sleeve top and dark shorts on a pink longboard."
    merged = identity._merge_compatible_structured_clusters([
        {"description": same, "appearances": [app("DJI_0143_D.MP4", a_desc, 10001)], "_visual_verified": True},
        {"description": same, "appearances": [app("DJI_0152_D.MP4", b_desc, 10046)]},
    ])
    if len(merged) != 1:
        raise SystemExit("fixture: these two descriptions merge on text")
    if merged[0].get("_visual_verified"):
        raise SystemExit("a merge on text descriptions must not be marked visually verified")
    if merged[0].get("_structured_merge") is not True:
        raise SystemExit("a text merge must say what it is")

    from pipeline.real_identity_gate import enforce_identity_gate

    gated = enforce_identity_gate(merged)
    if gated[0].get("_identity_gate") == "pass":
        raise SystemExit(f"an unconfirmed cross-source cluster passed the identity gate: {gated[0].get('_identity_gate_reason')}")

    # The verifier is asked even when the descriptions agree; without thumbnails it cannot confirm.
    calls: list[int] = []
    identity.genai = types.SimpleNamespace(
        upload_file=lambda **_k: calls.append(1) or object(),
        delete_file=lambda *_a, **_k: None,
        GenerativeModel=lambda **_k: None,
    )
    out = identity._verify_multi_clusters([{"description": same, "appearances": [
        app("DJI_0143_D.MP4", a_desc, 10001), app("DJI_0152_D.MP4", b_desc, 10046)]}])
    if any(c.get("_visual_verified") for c in out):
        raise SystemExit("no image was checked, so nothing may be marked visually verified")

    # ---- M2: unconfirmed identity blocks publication
    from pipeline import publishable_reel_policy as policy

    events = [event for a in gated[0]["appearances"] for event in a["events"]]
    reasons = policy.qa_gate_block_reasons(events)
    if gated[0].get("_identity_gate") == "kept_together_unconfirmed" and not any("IDENTITY_UNCONFIRMED" in r for r in reasons):
        raise SystemExit(f"an unconfirmed identity must block publication, got {reasons}")
    if policy.qa_gate_block_reasons([{"identity_gate": {"decision": "pass"}}]):
        raise SystemExit("a confirmed identity is not a block")

    # ---- M4: canonical event id
    from pipeline.event_identity import assign_session_event_uids, ensure_event_uid

    session = {"persons": [{"id": "person_A", "events": [
        {"type": "wave_catch", "start": 0.5, "end": 7.4, "score": 9},
        {"type": "wave_catch", "start": 9.0, "end": 15.0, "score": 7}]}]}
    if assign_session_event_uids(session, "/tmp/x/DJI_0151_D.MP4") != 2:
        raise SystemExit("every analyzed event must get an id")
    first, second = session["persons"][0]["events"]
    if not first["event_uid"].startswith("ev_") or first["event_uid"] == second["event_uid"]:
        raise SystemExit("ids must exist and differ per event")
    uid = first["event_uid"]
    revised = {**first, "start": 0.5, "end": 6.13}          # window refinement shortens the event
    if ensure_event_uid(revised, "/elsewhere/DJI_0151_D.MP4") != uid or revised["analyzer_window"] != {"start": 0.5, "end": 7.4}:
        raise SystemExit("a revised window must keep the id and the analyzer's original window")
    again = {"persons": [{"id": "person_A", "events": [{"type": "wave_catch", "start": 0.5, "end": 7.4, "score": 9}]}]}
    assign_session_event_uids(again, "DJI_0151_D.MP4")
    if again["persons"][0]["events"][0]["event_uid"] != uid:
        raise SystemExit("the id must be the same on a re-run of the same analysis")
    given = {"event_id": "evt-7", "start": 0, "end": 1}
    if ensure_event_uid(given, "x.mp4") != "evt-7":
        raise SystemExit("an id set upstream is kept")

    # ---- M5: reprocess requests close by id and by result
    from pipeline import orchestrator

    queued = [{"id": "req-pass", "sources": ["DJI_0112_D.MP4"]}, {"id": "req-fail", "sources": ["DJI_0151_D.MP4"]}]
    manifest = {"athletes": [
        {"primary_publishable_reel": "DRAFT_a.mp4", "action_lineage": ["/tmp/DJI_0112_D.MP4|1.500|19.500|wave_catch"]},
        {"primary_publishable_reel": None, "action_lineage": ["/tmp/DJI_0151_D.MP4|0.500|6.134|wave_catch"]}]}
    outcomes = orchestrator.reprocess_outcomes(queued, manifest)
    if outcomes != {"req-pass": True, "req-fail": False}:
        raise SystemExit(f"each request is judged by its own sources: {outcomes}")

    updates: list[tuple[dict, list[tuple[str, str]]]] = []

    class Query:
        def __init__(self, payload): self.payload, self.filters = payload, []
        def eq(self, key, value): self.filters.append((key, value)); return self
        def execute(self): updates.append((self.payload, self.filters)); return types.SimpleNamespace(data=[])

    fake = types.SimpleNamespace(table=lambda _n: types.SimpleNamespace(update=lambda payload: Query(payload)))
    sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *_a, **_k: fake, Client=object))
    from integrations import supabase_uploader as up

    up._supabase = lambda: fake
    written = up.close_reprocess_requests(outcomes)
    if written != {"req-pass": "done", "req-fail": "reprocessed_unverified"}:
        raise SystemExit(f"a re-edit that did not pass is not 'done': {written}")
    for payload, filters in updates:
        ids = [value for key, value in filters if key == "id"]
        if len(ids) != 1 or ("status", "queued") not in filters:
            raise SystemExit(f"every update must name one request id and only touch queued rows: {filters}")
    before = len(updates)
    up.close_queued_reprocess()
    if len(updates) != before:
        raise SystemExit("closing without request ids must change nothing")

    # ---- M1: typed admission
    from pipeline.performance_reel_policy import classify_event_eligibility, keep_event_for_performance_reel

    cases = (
        ({"type": "wave_catch", "score": 9, "description": "Rides a wave, making a smooth turn before falling."}, "ELIGIBLE", True),
        ({"type": "wave_catch", "score": 5, "description": "Rides the whitewater."}, "UNCERTAIN", True),
        ({"type": "wave_catch", "score": 8, "description": "Failed takeoff, falls immediately."}, "INELIGIBLE", False),
        ({"type": "highlight", "score": 4, "description": "Jumps."}, "INELIGIBLE", False),
    )
    for event, verdict, kept in cases:
        got = classify_event_eligibility(event, "surfing" if event["type"] == "wave_catch" else "parkour")
        if got["verdict"] != verdict or not got["basis"]:
            raise SystemExit(f"{event['description']!r}: expected {verdict}, got {got}")
        if keep_event_for_performance_reel(event, "surfing" if event["type"] == "wave_catch" else "parkour") != kept:
            raise SystemExit(f"admission changed for {event['description']!r}")
        if event.get("eligibility", {}).get("verdict") != verdict:
            raise SystemExit("the verdict must be stamped on the event")

    print("PASS: root-cause fixes (identity evidence, event id, reprocess lifecycle, typed admission)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

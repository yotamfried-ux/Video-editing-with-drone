#!/usr/bin/env python3
"""Root-cause fixes from the deep verification of 2026-11-15 (PR #387), one assertion per confirmed mechanism.

M2  A cluster is "_visual_verified" only when the image verifier confirmed it. Agreement between text
    descriptions does not set it, and a text merge clears an earlier confirmation.
    Run 43710581656: 0143 + 0152 passed the identity gate as "visual_verified_per_source_tracks" although the
    verifier was never shown an image of the pair.
M2  A multi-source cluster the gate keeps together without confirmation is not publishable.
M4  Every event gets a canonical id when it is created; a later window change does not change it.
M2  The same tracker number in two sources is not identity evidence (tested in test_real_identity_gate_contract).
M2  A merge decided on one image per cluster does not confirm a cluster with more members.
M5  A run closes only the reprocess requests it consumed. A request is verified only when every reel from its
    sources is publishable, so a good reel of another athlete in the same source does not close it.
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

    # ---- M2: a check of two images does not confirm a merged cluster with more members
    import os as _os
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as folder:
        def with_thumb(name: str, description: str, track: int) -> dict:
            thumb = _os.path.join(folder, name + ".jpg")
            open(thumb, "wb").write(b"jpg")
            return {**app(name, description, track), "thumbnail": thumb, "_sheet_crops": 6, "_sheet_crops": 6}

        import _consensus_fixture as fx
        identity._consensus_ask = lambda prompt, images: fx.MATCH_SPECIFIC
        identity._merge_check_pairs = lambda _clusters: [(0.8, 0, 1)]
        d = "Shirtless surfer in dark shorts on a light blue longboard."
        two_plus_one = identity._verify_merge_candidates([
            {"description": d, "_visual_verified": True, "appearances": [
                with_thumb("DJI_0097_D.MP4", d, 1), with_thumb("DJI_0115_D.MP4", d, 2)]},
            {"description": d, "appearances": [with_thumb("DJI_0130_D.MP4", d, 3)]},
        ])
        if len(two_plus_one) != 1 or len(two_plus_one[0]["appearances"]) != 3:
            raise SystemExit("fixture: the pair check merges the two clusters")
        if two_plus_one[0].get("_visual_verified"):
            raise SystemExit("one image per cluster was compared; a three-member cluster is not confirmed by that")
        one_plus_one = identity._verify_merge_candidates([
            {"description": d, "appearances": [with_thumb("DJI_0097_D.MP4", d, 1)]},
            {"description": d, "appearances": [with_thumb("DJI_0115_D.MP4", d, 2)]},
        ])
        if one_plus_one[0].get("_visual_verified") is not True:
            raise SystemExit("two single appearances compared directly are confirmed by that comparison")

    # ---- M2: unconfirmed identity blocks publication
    from pipeline import publishable_reel_policy as policy

    events = [event for a in gated[0]["appearances"] for event in a["events"]]
    reasons = policy.qa_gate_block_reasons(events)
    if gated[0].get("_identity_gate") == "kept_together_unconfirmed" and not any("IDENTITY_UNCONFIRMED" in r for r in reasons):
        raise SystemExit(f"an unconfirmed identity must block publication, got {reasons}")
    if policy.qa_gate_block_reasons([{"identity_gate": {"decision": "pass"}}]):
        raise SystemExit("a confirmed identity is not a block")

    # ---- M4: canonical event id (content hash + ordinal + schema; no timestamps)
    import tempfile
    from pipeline.event_identity import UID_SCHEMA, assign_session_event_uids, ensure_event_uid

    with tempfile.TemporaryDirectory() as folder:
        one, two, renamed = (Path(folder) / n for n in ("a/DJI_0151_D.MP4", "b/DJI_0151_D.MP4", "c/other_name.MP4"))
        for path, data in ((one, b"video-one"), (two, b"video-two"), (renamed, b"video-one")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        def analyzed(path: Path) -> list[dict]:
            # Two events of one person whose windows are equal after rounding to two decimals.
            session = {"persons": [{"id": "person_A", "events": [
                {"type": "wave_catch", "start": 0.501, "end": 7.401, "score": 9},
                {"type": "wave_catch", "start": 0.499, "end": 7.399, "score": 7}]}]}
            if assign_session_event_uids(session, str(path)) != 2:
                raise SystemExit("every analyzed event must get an id")
            return session["persons"][0]["events"]

        first, second = analyzed(one)
        if first["event_uid"] == second["event_uid"]:
            raise SystemExit("two events with the same rounded window must get different ids")
        if first["event_uid_schema"] != UID_SCHEMA or not first["event_source_ref"].startswith("sha256:"):
            raise SystemExit("the id must carry its schema version and the source's content hash")
        if analyzed(two)[0]["event_uid"] == first["event_uid"]:
            raise SystemExit("two different videos with the same file name must not share event ids")
        if analyzed(renamed)[0]["event_uid"] != first["event_uid"]:
            raise SystemExit("the same video under another name is the same source")
        if analyzed(one)[0]["event_uid"] != first["event_uid"]:
            raise SystemExit("the id must be the same on a re-run of the same analysis")
        uid = first["event_uid"]
        revised = {**first, "start": 0.5, "end": 6.13}      # window refinement shortens the event
        if ensure_event_uid(revised, str(two)) != uid or revised["analyzer_window"] != {"start": 0.501, "end": 7.401}:
            raise SystemExit("a revised window must keep the id and the analyzer's original window")
    given = {"event_id": "evt-7", "start": 0, "end": 1}
    if ensure_event_uid(given, "x.mp4") != "evt-7":
        raise SystemExit("an id set upstream is kept")

    # ---- M5: reprocess requests close by id and by result
    from pipeline import orchestrator

    def row(source: str, publishable: bool) -> dict:
        return {"primary_publishable_reel": "DRAFT.mp4" if publishable else None,
                "parts": [{"publishable": publishable}],
                "action_lineage": [f"/tmp/{source}|1.000|9.000|wave_catch"]}

    queued = [{"id": "req-pass", "sources": ["DJI_0112_D.MP4"]},
              {"id": "req-fail", "sources": ["DJI_0151_D.MP4"]},
              # Two athletes share this source: one reel is fine, the other is still blocked.
              {"id": "req-shared", "sources": ["DJI_0094_D.MP4"]},
              {"id": "req-no-output", "sources": ["DJI_0999_D.MP4"]}]
    manifest = {"athletes": [row("DJI_0112_D.MP4", True), row("DJI_0151_D.MP4", False),
                             row("DJI_0094_D.MP4", True), row("DJI_0094_D.MP4", False)]}
    # Unbound (historical) requests are never closed as done automatically, even when every reel from their
    # sources is publishable: they go to manual reconciliation (pipeline.reprocess_binding, PR #390 review).
    verdicts = orchestrator.reprocess_verdicts(queued, manifest)
    if any(v["verified"] or v["reason"] != "legacy_manual_reconciliation_required" for v in verdicts.values()):
        raise SystemExit(f"an unbound request must never close as done: {verdicts}")
    outcomes = {"req-pass": True, "req-fail": False}

    updates: list[tuple[dict, list[tuple[str, str]]]] = []

    class Query:
        def __init__(self, payload): self.payload, self.filters = payload, []
        def eq(self, key, value): self.filters.append((key, value)); return self
        def execute(self):
            updates.append((self.payload, self.filters))
            f = dict(self.filters)
            return types.SimpleNamespace(data=[{"id": f.get("id"), "last_pipeline_run_id": f.get("last_pipeline_run_id"),
                                                **self.payload}])

    fake = types.SimpleNamespace(table=lambda _n: types.SimpleNamespace(update=lambda payload: Query(payload)))
    sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *_a, **_k: fake, Client=object))
    from integrations import supabase_uploader as up

    up._supabase = lambda: fake
    written = up.close_reprocess_requests(outcomes, "run-1")
    if written != {"req-pass": "done", "req-fail": "reprocessed_unverified"}:
        raise SystemExit(f"a re-edit that did not pass is not 'done': {written}")
    for payload, filters in updates:
        ids = [value for key, value in filters if key == "id"]
        if len(ids) != 1 or ("status", "queued") not in filters or ("last_pipeline_run_id", "run-1") not in filters:
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

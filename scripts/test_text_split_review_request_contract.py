#!/usr/bin/env python3
"""Cycle 10 FIX-PQ-10-003 (PA-08, 0097+0115): a model-proposed grouping split ONLY on text attributes becomes an
identity review request; the owner's decision, not a model, can keep it together.

R1  0097/0115-like cluster ("dark swimsuit" vs "no shirt"), no decision -> split (as before) AND a PENDING review
    request is recorded in the identity trace with the text-attribute reason.
R2  the owner APPROVES that request_id -> one cluster with operator_review evidence; the identity gate passes it.
R3  the owner REJECTS -> split, no new request.
R4  a same-clip conflict is never reviewable that way: split even with an approval file present.
R5  a cluster without any conflict is untouched and no request is recorded.
R6  no model call is made on any path.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import identity_evidence as ev  # noqa: E402
from pipeline import identity_review as review  # noqa: E402
from pipeline import identity_trace  # noqa: E402
from pipeline.real_identity_gate import enforce_identity_gate  # noqa: E402
from pipeline.stages import identity  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def app(tmp: str, name: str, desc: str, idx: int, pid: str = "person_A", clip: int | None = None) -> dict:
    thumb = Path(tmp) / f"{name}_{pid}.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + (name + pid).encode())
    src = Path(tmp) / f"2026-10-03T12-19-53_DJI_2026072016_{name}_D.MP4"
    if not src.exists():
        src.write_bytes(b"source-bytes-" + name.encode())
    return {"path": str(src), "_clip_index": idx if clip is None else clip,
            "_person_id": pid, "thumbnail": str(thumb), "_sheet_crops": 6, "_description": desc,
            "events": [{"type": "wave_catch", "person_id": pid, "start": 1.0, "end": 8.0, "track_id": str(10001 + idx)}]}


def requests_recorded() -> list[dict]:
    meta = identity_trace.snapshot() if hasattr(identity_trace, "snapshot") else {}
    return [v for k, v in (meta or {}).items() if str(k).startswith("identity_review_")]


def main() -> int:
    calls = []
    saved = identity._consensus_ask
    identity._consensus_ask = lambda *a, **k: calls.append(1) or ""
    with tempfile.TemporaryDirectory() as tmp:
        decisions = Path(tmp) / "decisions.json"
        os.environ[review.DECISIONS_ENV] = str(decisions)
        os.environ["TMP_DIR"] = tmp

        def pair():
            return {"description": "Shirtless man in patterned shorts on a light blue surfboard.",
                    "appearances": [app(tmp, "0097", "surfer in dark swimsuit on a light-colored surfboard", 0),
                                    app(tmp, "0115", "surfer with dark shorts, no shirt, on a light blue surfboard", 1)]}

        recorded: list[dict] = []
        orig = review.record_request
        review.record_request = lambda r: (recorded.append(r), orig(r))
        out = identity._split_impossible_clusters([pair()])
        check(len(out) == 2, f"R1 no decision: split as before ({len(out)} clusters)")
        check(len(recorded) == 1 and "text attributes" in recorded[0]["reason"] and recorded[0]["status"] == "PENDING",
              f"R1 a PENDING review request with the text-attribute reason ({[r.get('reason') for r in recorded]})")
        rid = recorded[0]["request_id"] if recorded else "x" * 64
        check(recorded and recorded[0]["approvable"] is True, "R1 the request is approvable (strong source identities)")

        decisions.write_text(json.dumps({"decisions": [{"request_id": rid, "decision": "APPROVED", "reviewer": "owner",
                                                        "decided_at": "2026-11-18T00:00:00Z"}]}))
        recorded.clear()
        out = identity._split_impossible_clusters([pair()])
        check(len(out) == 1 and ev.covers(out[0]) and out[0][ev.EVIDENCE_KEY]["method"] == ev.OPERATOR_REVIEW,
              "R2 approved: one cluster with operator_review evidence")
        check(enforce_identity_gate(out)[0].get("_identity_gate") == "pass", "R2 the identity gate passes the owner-approved cluster")

        decisions.write_text(json.dumps({"decisions": [{"request_id": rid, "decision": "REJECTED", "reviewer": "owner",
                                                        "decided_at": "2026-11-18T00:00:00Z"}]}))
        out = identity._split_impossible_clusters([pair()])
        check(len(out) == 2 and not recorded, "R3 rejected: split, no new request")

        same = {"description": "x", "appearances": [app(tmp, "0200", "surfer in dark swimsuit", 0, "person_A", clip=5),
                                                    app(tmp, "0200", "surfer with no shirt", 1, "person_B", clip=5)]}
        same_rid = review.request_id(same)
        decisions.write_text(json.dumps({"decisions": [{"request_id": same_rid, "decision": "APPROVED", "reviewer": "owner",
                                                        "decided_at": "2026-11-18T00:00:00Z"}]}))
        check(len(identity._split_impossible_clusters([same])) == 2, "R4 same-clip conflict splits even with an approval")

        recorded.clear()
        ok = {"description": "y", "appearances": [app(tmp, "0160", "Woman in a green bikini on a white surfboard", 0),
                                                  app(tmp, "0163", "Woman in a green bikini on a white surfboard", 1)]}
        check(len(identity._split_impossible_clusters([ok])) == 1 and not recorded, "R5 no conflict: untouched, no request")
        review.record_request = orig
    identity._consensus_ask = saved
    check(not calls, "R6 no model call on any path")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

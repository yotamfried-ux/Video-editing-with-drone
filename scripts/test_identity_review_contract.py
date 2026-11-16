#!/usr/bin/env python3
"""REVIEW requests and the owner's decisions (fake verifier, real temp files so source identities are SHA-256).

R1  A doubtful cluster yields a PENDING request: exact sources, proposed identity, reason, pair evidence with both response
    digests, model, prompt digest; recorded in the identity trace.
R2  Without a decision nothing is published or dropped: all appearances and events are kept, the gate says
    kept_together_unconfirmed, no evidence is stamped.
R3  An APPROVED decision for exactly these sources stamps operator evidence; the gate passes it (also after the strip).
R4  A decision for other members (one more source / different file bytes) never applies; the lookalike (0143+0152-like) pair
    stays PENDING unless a decision names exactly its request id.
R5  REJECTED splits the cluster into single appearances.
R6  A weak source identity (unreadable file, name only) can never be approved. Malformed decision files are ignored.
R7  No Ground Truth access and no automatic decision writing in the review modules.
R8  Tampering with operator evidence (reviewer removed, members changed) makes it uncovered.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import _consensus_fixture as fx  # noqa: E402
from pipeline import event_identity, identity_evidence as ev, identity_review as review  # noqa: E402
from pipeline.real_identity_gate import enforce_identity_gate  # noqa: E402
from pipeline.stages import identity  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def make(tmp: str, names: list[str], real: bool = True) -> dict:
    apps = []
    for i, name in enumerate(names):
        video = Path(tmp) / f"{name}.MP4"
        if real:
            video.write_bytes(b"video-" + name.encode())
        thumb = Path(tmp) / f"{name}.jpg"
        thumb.write_bytes(b"\xff\xd8\xff" + name.encode())
        apps.append({"path": str(video), "_person_id": "person_A", "thumbnail": str(thumb),
                     "events": [{"type": "wave_catch", "person_id": "person_A", "start": 1.0, "end": 8.0, "track_id": str(10000 + i)}]})
    return {"description": "surfer on a pink board", "appearances": apps}


def decision_file(tmp: str, request_id: str, decision: str = "APPROVED") -> str:
    path = Path(tmp) / "decisions.json"
    path.write_text(json.dumps({"decisions": [{"request_id": request_id, "decision": decision, "reviewer": "owner",
                                               "decided_at": "2026-11-17T00:00:00Z", "note": "checked on the footage"}]}))
    return str(path)


def verify(cluster, answer):
    saved = identity._consensus_ask
    identity._consensus_ask = fx.ask_with(answer)
    try:
        return identity._verify_multi_clusters([cluster])
    finally:
        identity._consensus_ask = saved


def setup_env(path: str | None):
    import os
    event_identity.reset_for_tests()
    if path:
        os.environ[review.DECISIONS_ENV] = path
    else:
        os.environ[review.DECISIONS_ENV] = "/nonexistent/decisions.json"


def r1_r2():
    with tempfile.TemporaryDirectory() as tmp:
        setup_env(None)
        cl = make(tmp, ["A_0143", "B_0152"])
        before = copy.deepcopy(cl["appearances"])
        out = verify(cl, fx.MATCH_GENERIC)
        check(len(out) == 1 and not ev.covers(out[0]) and not out[0].get("_visual_verified"), "R2 stamped without a decision")
        check(len(out[0]["appearances"]) == 2 and [a["events"] for a in out[0]["appearances"]] == [a["events"] for a in before],
              "R2 appearances/events must be kept untouched")
        g = enforce_identity_gate(out)
        check(g[0]["_identity_gate"] == "kept_together_unconfirmed" and len(g[0]["appearances"]) == 2, "R2 gate")
        rid = out[0].get("_identity_review")
        check(isinstance(rid, str) and len(rid) == 64, "R1 request id on the cluster")
        # build the request again exactly like production does
        from pipeline import identity_pair_consensus as pc
        res = pc.verify_cluster(cl, fx.ask_with(fx.MATCH_GENERIC))
        req = review.build_request(cl, res, model="gemini-2.5-flash", prompt=pc.M1_PROMPT)
        check(req["request_id"] == rid and req["status"] == "PENDING" and req["approvable"], "R1 request header")
        check(len(req["sources"]) == 2 and all(s["source"].startswith("sha256:") for s in req["sources"]), "R1 sources are SHA-256")
        check(req["proposed_identity"]["description"] and req["reason"] and req["model"] and len(req["prompt_sha256"]) == 64, "R1 fields")
        check(req["pair_evidence"] and all(len(p["forward_sha256"]) == 64 and len(p["backward_sha256"]) == 64 for p in req["pair_evidence"]),
              "R1 pair evidence carries both response digests")


def r3():
    with tempfile.TemporaryDirectory() as tmp:
        setup_env(None)
        cl = make(tmp, ["A_0160", "B_0163"])
        rid = review.request_id(cl)
        setup_env(decision_file(tmp, rid))
        out = verify(make(tmp, ["A_0160", "B_0163"]), fx.UNCERTAIN)
        check(len(out) == 1 and ev.covers(out[0]) and out[0]["_identity_evidence"]["method"] == "operator_review", "R3 approval stamps")
        check(enforce_identity_gate(out)[0]["_identity_gate"] == "pass", "R3 gate passes")
        stripped = identity._strip_internal_fields(out)
        check(ev.covers(stripped[0]) and enforce_identity_gate(stripped)[0]["_identity_gate"] == "pass", "R3 survives the strip")


def r4_r5():
    with tempfile.TemporaryDirectory() as tmp:
        setup_env(None)
        approved = review.request_id(make(tmp, ["A", "B"]))
        setup_env(decision_file(tmp, approved))
        out = verify(make(tmp, ["A", "B", "C"]), fx.UNCERTAIN)           # one more source: other request id
        check(len(out) == 1 and not ev.covers(out[0]), "R4 approval must not extend to an added source")
        other = make(tmp, ["A", "B"])
        (Path(tmp) / "A.MP4").write_bytes(b"other bytes")               # same names, different content
        event_identity.reset_for_tests()
        out = verify(other, fx.UNCERTAIN)
        check(not ev.covers(out[0]), "R4 approval must not apply to different file content")
        # lookalike stays pending without its own decision
        event_identity.reset_for_tests()
        look = make(tmp, ["P_0143", "Q_0152"])
        out = verify(look, fx.MATCH_GENERIC)
        check(not ev.covers(out[0]) and enforce_identity_gate(out)[0]["_identity_gate"] == "kept_together_unconfirmed", "R4 lookalike")
        # rejection splits
        setup_env(decision_file(tmp, review.request_id(make(tmp, ["P_0143", "Q_0152"])), "REJECTED"))
        event_identity.reset_for_tests()
        out = verify(make(tmp, ["P_0143", "Q_0152"]), fx.MATCH_GENERIC)
        check(len(out) == 2 and not any(ev.covers(c) for c in out), "R5 REJECTED must split")


def r6():
    with tempfile.TemporaryDirectory() as tmp:
        setup_env(None)
        weak = make(tmp, ["A", "B"], real=False)                          # video files do not exist: name-only identity
        rid = review.request_id(weak)
        setup_env(decision_file(tmp, rid))
        out = verify(make(tmp, ["A", "B"], real=False), fx.UNCERTAIN)
        check(not ev.covers(out[0]), "R6 a weak source identity must never be approvable")
        bad = Path(tmp) / "bad.json"
        for payload in ("not json", "[]", json.dumps({"decisions": [{"request_id": "x", "decision": "APPROVED"}]}),
                        json.dumps({"decisions": [{"request_id": "a" * 64, "decision": "MAYBE", "reviewer": "o", "decided_at": "t"}]}),
                        json.dumps({"decisions": [{"request_id": "a" * 64, "decision": "APPROVED", "reviewer": "", "decided_at": "t"}]})):
            bad.write_text(payload)
            check(review.load_decisions(bad) == {}, f"R6 malformed decisions must be ignored: {payload[:40]}")


def r7():
    for f in ("pipeline/identity_review.py", "pipeline/identity_pair_consensus.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        check("ground_truth" not in src.lower() and "gtv1" not in src.lower(), f"R7 {f} touches the GT")
        import re
        opens = [ln.strip() for ln in src.splitlines() if re.search(r"(?<![a-z_])open\(", ln) and '"rb"' not in ln]
        check("write_text" not in src and "write_bytes" not in src and not opens, f"R7 {f} writes files: {opens}")


def r8():
    with tempfile.TemporaryDirectory() as tmp:
        setup_env(None)
        cl = make(tmp, ["A", "B"])
        setup_env(decision_file(tmp, review.request_id(cl)))
        out = verify(make(tmp, ["A", "B"]), fx.UNCERTAIN)[0]
        check(ev.covers(out), "R8 fixture")
        t = copy.deepcopy(out); t["_identity_evidence"]["reviewer"] = ""
        check(not ev.covers(t), "R8 edited reviewer must break the digest")
        t = copy.deepcopy(out); t["_identity_evidence"]["reviewer"] = ""; t["_identity_evidence"]["evidence_digest"] = ev._evidence_digest(t["_identity_evidence"])
        check(ev.coverage_problem(t) == "operator_decision_incomplete", "R8 incomplete decision")
        t = copy.deepcopy(out); t["appearances"].append(make(tmp, ["Z"])["appearances"][0])
        check(not ev.covers(t), "R8 member added after approval")


for case in (r1_r2, r3, r4_r5, r6, r7, r8):
    try:
        case()
    except Exception as exc:
        import traceback
        FAILURES.append(f"{case.__name__} crashed: {exc!r}\n{traceback.format_exc()[-500:]}")
if FAILURES:
    print("\n".join("FAIL " + f for f in FAILURES))
    sys.exit(1)
print("identity review contract: all cases passed")

"""REVIEW requests for cross-clip identity merges that the pairwise consensus could not confirm.

The system owner approves or rejects them (a decision file under evaluation/identity_reviews/, or the path in
SPORTREEL_IDENTITY_REVIEW_DECISIONS). Until a decision exists the cluster stays together, unconfirmed and withheld: nothing
is published, nothing is dropped, nothing is re-cut. A decision is bound to the EXACT sources and people of the cluster
(request_id), never to model output, and nothing here ever writes the Ground Truth or a decision.

request record: request_id | status | sources (file, source identity) | proposed identity | reason | pair evidence
(decisions, features, response digests of both image orders) | model | prompt digest.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DECISIONS_ENV = "SPORTREEL_IDENTITY_REVIEW_DECISIONS"
DEFAULT_DECISIONS = ROOT / "evaluation" / "identity_reviews" / "decisions.json"
VALID = {"APPROVED", "REJECTED"}


def source_identity(app: dict[str, Any]) -> tuple[str, bool]:
    """(identity, strong): the content SHA-256 of the source video, or its file name (weak: never approvable)."""
    from pipeline import event_identity

    kind, value = event_identity.source_ref(str(app.get("path") or ""))
    return f"{kind}:{value}", kind == "sha256"


def _member(app: dict[str, Any]) -> dict[str, Any]:
    from pipeline import identity_evidence as ev

    ident, strong = source_identity(app)
    return {"file": os.path.basename(str(app.get("path") or "")), "source": ident, "strong_source_identity": strong,
            "person": ev.member_key(app).split("::", 1)[-1]}


def request_id(cluster: dict[str, Any]) -> str:
    members = sorted(f"{m['source']}::{m['person']}" for m in map(_member, cluster.get("appearances") or []))
    return hashlib.sha256(json.dumps(members).encode("utf-8")).hexdigest()


def build_request(cluster: dict[str, Any], result: dict[str, Any], *, model: str, prompt: str, run_id: str = "") -> dict[str, Any]:
    members = [_member(a) for a in cluster.get("appearances") or []]
    return {
        "schema": "sportreel.identity_review_request.v1",
        "request_id": request_id(cluster),
        "status": "PENDING",
        "run_id": run_id or os.getenv("PIPELINE_RUN_ID", ""),
        "sources": members,
        "proposed_identity": {"description": str(cluster.get("description", ""))[:200],
                              "claim": "all listed appearances are the same athlete"},
        "reason": result.get("reason") or "pairwise consensus not reached",
        "pair_evidence": [{"a": p.get("a"), "b": p.get("b"), "decision": p.get("decision"),
                           "matching_features": p.get("matching_features"), "contradicting_features": p.get("contradicting_features"),
                           "forward_sha256": p.get("forward_sha256"), "backward_sha256": p.get("backward_sha256")}
                          for p in result.get("pairs") or []],
        "model": model,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "approvable": all(m["strong_source_identity"] for m in members),
    }


def load_decisions(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """request_id -> decision. Malformed files / records are ignored (fail closed); the latest valid record wins."""
    target = Path(path or os.getenv(DECISIONS_ENV) or DEFAULT_DECISIONS)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in raw.get("decisions", []) if isinstance(raw, dict) else []:
        if (isinstance(item, dict) and item.get("decision") in VALID and len(str(item.get("request_id") or "")) == 64
                and str(item.get("reviewer") or "").strip() and str(item.get("decided_at") or "").strip()):
            out[item["request_id"]] = item
    return out


def record_request(request: dict[str, Any]) -> None:
    """Write the request into the run's identity trace (part of the diagnostics artifact)."""
    try:
        from pipeline import identity_trace

        identity_trace.record_metadata(f"identity_review_{request['request_id'][:12]}", request)
    except Exception:  # noqa: BLE001 - recording must never break the run
        pass


def resolve(cluster: dict[str, Any], request: dict[str, Any], decisions: dict[str, dict[str, Any]] | None = None) -> str:
    """APPROVED | REJECTED | PENDING. An approval for weak source identities (file names only) is refused."""
    decision = (decisions if decisions is not None else load_decisions()).get(request["request_id"])
    if not decision:
        return "PENDING"
    if decision["decision"] == "APPROVED" and not request.get("approvable"):
        return "PENDING"
    return decision["decision"]

"""Verification evidence bound to the exact membership of an athlete cluster.

A `_visual_verified` boolean says nothing about *which* appearances were checked. A cluster that gains or loses a
member after the check keeps the flag although the check no longer covers it. Here a positive image verification
records the member set it covered (and a hash of it); the release gate accepts a cluster as visually verified only
when that recorded set is exactly the cluster's current membership.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

EVIDENCE_KEY = "_identity_evidence"
IMAGE_VERIFIER = "image_verifier"
PAIR_CHECK_SINGLETONS = "pair_check_singletons"
ACCEPTED_METHODS = {IMAGE_VERIFIER, PAIR_CHECK_SINGLETONS}


def member_key(app: dict[str, Any]) -> str:
    """Stable key of one appearance: its source file and the person inside it.

    Works before and after `identity._strip_internal_fields` (which keeps only path and events). The source is
    the file name: `_clip_index` is a run-local integer that the strip removes, so a key built from it at
    verification time never matched the key built from the path at the release gate (run 43920602179: all five
    image-verified multi-source athletes were withheld as unconfirmed).
    """
    source = os.path.basename(str(app.get("path") or app.get("_clip_index") or ""))
    person = app.get("_person_id")
    if not person:
        person = next((str(e.get("person_id")) for e in app.get("events", []) or []
                       if isinstance(e, dict) and e.get("person_id")), "")
    return f"{source}::{person}"


def members(cluster: dict[str, Any]) -> list[str]:
    return sorted(member_key(app) for app in cluster.get("appearances", []) or [])


def members_hash(keys: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(keys)).encode("utf-8")).hexdigest()[:16]


def _file_sha256(path: Any) -> str:
    try:
        digest = hashlib.sha256()
        with open(str(path), "rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, TypeError):
        return ""


def _source_of(key: str) -> str:
    return key.split("::", 1)[0]


def _required_pairs(keys: list[str]) -> list[list[str]]:
    """Every pair of members from different source files: each needs a MATCH edge."""
    return [[a, b] for index, a in enumerate(keys) for b in keys[index + 1:] if _source_of(a) != _source_of(b)]


def _evidence_digest(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "evidence_digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def stamp(cluster: dict[str, Any], method: str, detail: str = "", *, images: list[Any] | None = None,
          model: str = "", raw_response: str = "", member_images: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record a positive image verification that covered exactly the cluster's current members.

    The record names what was examined: the SHA-256 of the image shown for every member, the model, a digest of
    the model's answer, a timestamp, and a MATCH edge for every cross-source pair (one group-wide call that saw all
    members' images, or one pairwise call for two singletons). Without an image for every member the record is
    still written - so the trace shows the attempt - but `covers` rejects it.
    """
    from datetime import datetime, timezone

    apps = list(cluster.get("appearances", []) or [])
    if member_images is None:
        member_images = {member_key(app): (images[i] if images and i < len(images) else app.get("thumbnail"))
                         for i, app in enumerate(apps)}
    keys = members(cluster)
    image_hashes = {key: _file_sha256(member_images.get(key)) for key in keys}
    record = {
        "schema": "sportreel.identity_evidence.v2",
        "method": method,
        "members": keys,
        "members_hash": members_hash(keys),
        "image_sha256": image_hashes,
        "model": str(model or ""),
        "response_sha256": hashlib.sha256(str(raw_response or "").encode("utf-8")).hexdigest() if raw_response else "",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "scope": "group" if method == IMAGE_VERIFIER else "pair",
        "pairwise": [{"a": a, "b": b, "verdict": "MATCH"} for a, b in _required_pairs(keys)],
        "detail": detail[:200],
    }
    record["evidence_digest"] = _evidence_digest(record)
    cluster[EVIDENCE_KEY] = record
    cluster["_visual_verified"] = True
    return cluster


def clear(cluster: dict[str, Any]) -> dict[str, Any]:
    cluster.pop(EVIDENCE_KEY, None)
    cluster.pop("_visual_verified", None)
    return cluster


def coverage_problem(cluster: dict[str, Any]) -> str:
    """Why the recorded evidence does not prove the cluster's identity, or "" when it does."""
    evidence = cluster.get(EVIDENCE_KEY)
    if not isinstance(evidence, dict):
        return "no_identity_evidence"
    if evidence.get("method") not in ACCEPTED_METHODS:
        return "unaccepted_method"
    keys = members(cluster)
    if not keys or evidence.get("members") != keys or evidence.get("members_hash") != members_hash(keys):
        return "evidence_does_not_cover_current_members"
    if evidence.get("evidence_digest") != _evidence_digest(evidence):
        return "evidence_record_altered"
    hashes = evidence.get("image_sha256") if isinstance(evidence.get("image_sha256"), dict) else {}
    if any(len(str(hashes.get(key) or "")) != 64 for key in keys):
        return "image_not_examined_for_every_member"
    if not evidence.get("model") or len(str(evidence.get("response_sha256") or "")) != 64:
        return "verifier_call_not_recorded"
    if evidence.get("method") == PAIR_CHECK_SINGLETONS and len(keys) != 2:
        return "pair_check_cannot_cover_more_than_two_members"
    edges = {(e.get("a"), e.get("b")) for e in evidence.get("pairwise") or []
             if isinstance(e, dict) and e.get("verdict") == "MATCH"}
    if any((a, b) not in edges for a, b in _required_pairs(keys)):
        return "cross_source_pair_without_match_edge"
    return ""


def covers(cluster: dict[str, Any]) -> bool:
    """True only when recorded image evidence proves every current member and nothing else."""
    return coverage_problem(cluster) == ""


def parse_verifier_verdict(parsed: Any, n_images: int) -> tuple[bool, set[int], str]:
    """Read the image verifier's answer strictly. Returns (confirmed, mismatched_indices, problem).

    Only an explicit `"same_person": true` with no mismatched image confirms identity. A missing or non-boolean
    `same_person`, a malformed `mismatched_indices`, or a contradictory answer is reported as a problem and
    never confirms anything. Before this, a missing `same_person` defaulted to "no mismatches listed", so an
    empty or truncated answer (`{}`) was read as a positive identity confirmation.
    """
    if not isinstance(parsed, dict):
        return False, set(), "verifier_response_not_object"
    same = parsed.get("same_person")
    if not isinstance(same, bool):
        return False, set(), "verifier_same_person_missing_or_not_boolean"
    raw = parsed.get("mismatched_indices", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return False, set(), "verifier_mismatched_indices_not_list"
    bad: set[int] = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < n_images:
            return False, set(), "verifier_mismatched_index_invalid"
        bad.add(item)
    if same and bad:
        return False, set(), "verifier_response_contradictory"
    return same, bad, ""

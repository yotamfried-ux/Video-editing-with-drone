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

    Works before and after `identity._strip_internal_fields` (which keeps only path and events).
    """
    source = os.path.basename(str(app.get("_clip_index") or app.get("path") or ""))
    person = app.get("_person_id")
    if not person:
        person = next((str(e.get("person_id")) for e in app.get("events", []) or []
                       if isinstance(e, dict) and e.get("person_id")), "")
    return f"{source}::{person}"


def members(cluster: dict[str, Any]) -> list[str]:
    return sorted(member_key(app) for app in cluster.get("appearances", []) or [])


def members_hash(keys: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(keys)).encode("utf-8")).hexdigest()[:16]


def stamp(cluster: dict[str, Any], method: str, detail: str = "") -> dict[str, Any]:
    """Record a positive verification that covered exactly the cluster's current members."""
    keys = members(cluster)
    cluster[EVIDENCE_KEY] = {"method": method, "members": keys, "members_hash": members_hash(keys), "detail": detail[:200]}
    cluster["_visual_verified"] = True
    return cluster


def clear(cluster: dict[str, Any]) -> dict[str, Any]:
    cluster.pop(EVIDENCE_KEY, None)
    cluster.pop("_visual_verified", None)
    return cluster


def covers(cluster: dict[str, Any]) -> bool:
    """True only when recorded image evidence covers every current member and nothing else."""
    evidence = cluster.get(EVIDENCE_KEY)
    if not isinstance(evidence, dict) or evidence.get("method") not in ACCEPTED_METHODS:
        return False
    keys = members(cluster)
    return bool(keys) and evidence.get("members") == keys and evidence.get("members_hash") == members_hash(keys)


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

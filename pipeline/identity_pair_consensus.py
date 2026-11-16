"""Pairwise cross-clip athlete identity decision rules (pure logic, no model or media access).

Cycle 3 measured this rule against GT-v1 (docs/production-readiness/CYCLE-03-IDENTITY-REPORT.md); cycle 4 wires it as
the ONLY route that can confirm a cross-clip merge (identity_evidence.PAIRWISE_CONSENSUS), together with the path-first
evidence key (the key fix alone would have released the 0143+0152 false merge).

Rule: an automatic MATCH needs BOTH image orders to say MATCH with >= 2 specific matching features, no cited
contradiction and not generic-only; an automatic NO_MATCH needs both orders to cite a contradiction; everything
else is REVIEW. REVIEW never merges.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Callable

M1_PROMPT = """\
Two images follow. Each is a contact sheet of crops of ONE tracked person, cut from a drone video of a different clip.
Decide whether the two people are the SAME athlete. Aerial footage: faces are not usable.
Compare only what is actually visible: board colour/shape/stripes/logos, wetsuit or rash-guard/top/shorts colours and
patterns, hair, body build, helmet/hat, leash, any numbers.
Generic traits shared by many surfers (dark shorts, light top, a longboard, a pink board of common shape) are NOT
enough to say MATCH. Look for contradictions as hard as for agreement.
Return ONLY JSON:
{"verdict": "MATCH|NO_MATCH|UNCERTAIN",
 "matching_features": ["specific feature visible in both"],
 "contradicting_features": ["feature that differs"],
 "generic_only": true|false}
Rules: MATCH needs at least two independent specific matching features and no contradiction. A clear contradiction
(different board colour or pattern, different top/shorts colour) is NO_MATCH. Otherwise UNCERTAIN."""


def parse_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def m0_decision(parsed: dict[str, Any] | None) -> str:
    """Production semantics: only an explicit boolean same_person confirms; anything else is not a merge."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("same_person"), bool):
        return "REVIEW"
    return "MATCH" if parsed["same_person"] else "NO_MATCH"


def _features(parsed: dict[str, Any] | None, key: str) -> list[str]:
    value = (parsed or {}).get(key)
    return [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []


def single_verdict(parsed: dict[str, Any] | None) -> str:
    """M1 verdict with its own self-consistency rules (a MATCH that cites a contradiction or < 2 features is UNCERTAIN)."""
    if not isinstance(parsed, dict):
        return "REVIEW"
    verdict = str(parsed.get("verdict", "")).upper()
    match, contra = _features(parsed, "matching_features"), _features(parsed, "contradicting_features")
    if verdict == "MATCH":
        return "MATCH" if len(match) >= 2 and not contra and parsed.get("generic_only") is not True else "REVIEW"
    if verdict == "NO_MATCH":
        return "NO_MATCH" if contra else "REVIEW"
    return "REVIEW"


def consensus(forward: dict[str, Any] | None, backward: dict[str, Any] | None) -> str:
    """M2: automatic MATCH / NO_MATCH only when BOTH image orders agree; every disagreement or doubt is REVIEW."""
    a, b = single_verdict(forward), single_verdict(backward)
    if a == b == "MATCH":
        return "MATCH"
    if a == b == "NO_MATCH":
        return "NO_MATCH"
    return "REVIEW"


# ------------------------------------------------------------------ production wiring (model access is injected)
Ask = Callable[[str, "list[bytes]"], str]       # (prompt, [image bytes]) -> raw model text; may raise


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def verify_pair(ask: Ask, sheet_a: bytes, sheet_b: bytes) -> dict[str, Any]:
    """Both image orders. Any error, empty or unparsable answer in either order is REVIEW, never a merge."""
    answers = []
    for first, second in ((sheet_a, sheet_b), (sheet_b, sheet_a)):
        try:
            raw = ask(M1_PROMPT, [first, second])
        except Exception:
            raw = ""
        answers.append((raw, parse_json(raw)))
    (raw_f, forward), (raw_b, backward) = answers
    return {"decision": consensus(forward, backward), "forward_sha256": _sha(raw_f) if raw_f else "",
            "backward_sha256": _sha(raw_b) if raw_b else "",
            "matching_features": _features(forward, "matching_features")[:4],
            "contradicting_features": (_features(forward, "contradicting_features")
                                       + _features(backward, "contradicting_features"))[:4]}


def _read(path: Any) -> bytes | None:
    try:
        with open(str(path), "rb") as handle:
            return handle.read() or None
    except (OSError, TypeError):
        return None


def verify_cluster(cluster: dict[str, Any], ask: Ask) -> dict[str, Any]:
    """Check EVERY cross-source pair of the cluster (no transitive merge). verdict: MATCH only if all are MATCH,
    NO_MATCH if any pair is a confident different-athlete, otherwise REVIEW."""
    from pipeline import identity_evidence as ev

    apps = list(cluster.get("appearances") or [])
    keys = [ev.member_key(a) for a in apps]
    images = {k: _read(a.get("thumbnail")) for k, a in zip(keys, apps)}
    if len(set(keys)) != len(keys) or any(v is None for v in images.values()):
        return {"verdict": "REVIEW", "reason": "ambiguous_member_keys_or_missing_images", "pairs": []}
    pairs = []
    for a, b in ev._required_pairs(sorted(keys)):
        result = verify_pair(ask, images[a], images[b])
        pairs.append(dict(result, a=a, b=b))
    decisions = {p["decision"] for p in pairs}
    verdict = "NO_MATCH" if "NO_MATCH" in decisions else ("MATCH" if pairs and decisions == {"MATCH"} else "REVIEW")
    return {"verdict": verdict, "reason": "", "pairs": pairs}


def verify_multi_clusters(clusters: list[dict[str, Any]], *, ask: Ask, split_to_singles: Callable[..., list],
                          model: str = "gemini-2.5-flash") -> list[dict[str, Any]]:
    """The one cluster verifier. MATCH -> pairwise evidence stamped; NO_MATCH -> split into single appearances;
    REVIEW (doubt, error, missing image) -> kept together WITHOUT evidence, so the identity gate withholds it."""
    from pipeline import identity_evidence as ev

    out: list[dict[str, Any]] = []
    for cluster in clusters:
        apps = cluster.get("appearances") or []
        if len(apps) < 2:
            out.append(cluster)
            continue
        if ev.covers(cluster):
            out.append(cluster)                    # already confirmed for exactly these members
            continue
        cluster = ev.clear(dict(cluster))
        result = verify_cluster(cluster, ask)
        if result["verdict"] == "MATCH":
            keys = [ev.member_key(a) for a in apps]
            images = {k: a.get("thumbnail") for k, a in zip(keys, apps)}
            out.append(ev.stamp_pairwise(dict(cluster), result["pairs"], model=model, member_images=images))
        elif result["verdict"] == "NO_MATCH":
            out.extend(split_to_singles(cluster, "pairwise consensus: a pair is a different athlete"))
        else:
            # REVIEW: a structured request for the owner; the cluster stays together, unconfirmed and withheld.
            from pipeline import identity_review as review

            request = review.build_request(cluster, result, model=model, prompt=M1_PROMPT)
            decision = review.resolve(cluster, request)
            if decision == "APPROVED":
                approved = review.load_decisions()[request["request_id"]]
                out.append(ev.stamp_operator_review(dict(cluster), approved, request_id=request["request_id"]))
            elif decision == "REJECTED":
                out.extend(split_to_singles(cluster, "owner rejected the review request"))
            else:
                review.record_request(request)
                out.append(dict(cluster, _identity_review=request["request_id"]))
    return out

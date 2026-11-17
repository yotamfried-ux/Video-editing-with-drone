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
from concurrent.futures import ThreadPoolExecutor
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


def workers() -> int:
    """Concurrent model calls (SPORTREEL_CONSENSUS_WORKERS, default 4; 1 = serial). Results never depend on it."""
    try:
        return max(1, min(16, int(os.environ.get("SPORTREEL_CONSENSUS_WORKERS", "4"))))
    except ValueError:
        return 4


def _ask_safe(ask: Ask, first: bytes, second: bytes) -> str:
    try:
        return ask(M1_PROMPT, [first, second])
    except Exception:
        return ""


def verify_pair(ask: Ask, sheet_a: bytes, sheet_b: bytes) -> dict[str, Any]:
    """Both image orders. Any error, empty or unparsable answer in either order is REVIEW, never a merge."""
    orders = ((sheet_a, sheet_b), (sheet_b, sheet_a))
    if workers() > 1:
        with ThreadPoolExecutor(max_workers=2) as pool:
            raws = list(pool.map(lambda o: _ask_safe(ask, *o), orders))
    else:
        raws = [_ask_safe(ask, *o) for o in orders]
    answers = [(raw, parse_json(raw)) for raw in raws]
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


MIN_SHEET_CROPS = 6      # the validated setting (cycle 5: four crops auto-matched 0143+0152)


def verify_cluster(cluster: dict[str, Any], ask: Ask) -> dict[str, Any]:
    """Check EVERY cross-source pair of the cluster (no transitive merge). verdict: MATCH only if all are MATCH,
    NO_MATCH if any pair is a confident different-athlete, otherwise REVIEW."""
    from pipeline import identity_evidence as ev

    apps = list(cluster.get("appearances") or [])
    keys = [ev.member_key(a) for a in apps]
    images = {k: _read(a.get("thumbnail")) for k, a in zip(keys, apps)}
    if len(set(keys)) != len(keys) or any(v is None for v in images.values()):
        return {"verdict": "REVIEW", "reason": "ambiguous_member_keys_or_missing_images", "pairs": []}
    thin = [k for k, a in zip(keys, apps) if int(a.get("_sheet_crops") or 0) < MIN_SHEET_CROPS]
    if thin:                                   # fail closed: a thinner sheet is not the evidence the rule was validated on
        return {"verdict": "REVIEW", "reason": f"identity_sheet_has_fewer_than_{MIN_SHEET_CROPS}_crops", "pairs": []}
    required = list(ev._required_pairs(sorted(keys)))
    if workers() > 1 and len(required) > 1:
        with ThreadPoolExecutor(max_workers=max(1, workers() // 2)) as pool:   # each pair already runs 2 calls
            results = list(pool.map(lambda ab: verify_pair(ask, images[ab[0]], images[ab[1]]), required))
    else:
        results = [verify_pair(ask, images[a], images[b]) for a, b in required]
    pairs = [dict(r, a=a, b=b) for (a, b), r in zip(required, results)]
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


SINGLETON_PAIRS_MAX_DEFAULT = 45     # 10 single-source clusters; measured 36 pairs = $0.19 (EXP-08-002)


def singleton_pairs_max() -> int:
    """SPORTREEL_SINGLETON_PAIRS_MAX (0 disables the stage)."""
    try:
        return max(0, int(os.environ.get("SPORTREEL_SINGLETON_PAIRS_MAX", str(SINGLETON_PAIRS_MAX_DEFAULT))))
    except ValueError:
        return SINGLETON_PAIRS_MAX_DEFAULT


def merge_verified_singletons(clusters: list[dict[str, Any]], *, ask: Ask, model: str = "gemini-2.5-flash",
                              max_pairs: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Propose cross-source pairs of SINGLE-SOURCE clusters to the same fail-closed pairwise verifier.

    Root cause (PA-08, 0097+0115): one athlete filmed in two clips under different light got two descriptions
    ("dark swimsuit" vs "no shirt"); the description-based clustering never put the clips together, so the
    pairwise verifier, which only checks clusters it is given, never saw the pair and the athlete got two reels.
    Here every cross-source pair of single-source clusters is verified (both image orders, production sheets).
    Clusters are merged only through MATCH edges, and a group grows only if EVERY pair inside it is a MATCH (no
    transitive merge); NO_MATCH / REVIEW / errors leave the clusters as they were (split = the previous behaviour).
    More candidate pairs than `max_pairs` -> the stage is skipped (cost bound), never a partial guess.
    Returns (clusters, report).
    """
    from pipeline import identity_evidence as ev

    limit = singleton_pairs_max() if max_pairs is None else max_pairs
    report: dict[str, Any] = {"stage": "singleton_pair_merge", "pairs": 0, "merged_groups": [], "skipped": ""}

    def sources(c: dict[str, Any]) -> set[str]:
        return {os.path.basename(str(a.get("path") or "")) for a in (c.get("appearances") or [])}

    singles = [i for i, c in enumerate(clusters) if len(c.get("appearances") or []) >= 1 and len(sources(c)) == 1]
    candidates = [(i, j) for k, i in enumerate(singles) for j in singles[k + 1:] if sources(clusters[i]) != sources(clusters[j])]
    if not candidates:
        return clusters, dict(report, skipped="no_candidate_pairs")
    if limit <= 0 or len(candidates) > limit:
        return clusters, dict(report, skipped=f"candidate_pairs_{len(candidates)}_over_limit_{limit}")
    verdicts: dict[tuple[int, int], dict[str, Any]] = {}
    for i, j in candidates:
        verdicts[(i, j)] = verify_cluster({"appearances": list(clusters[i]["appearances"]) + list(clusters[j]["appearances"])}, ask)
    report["pairs"] = len(candidates)
    report["verdicts"] = {f"{i}-{j}": v["verdict"] for (i, j), v in verdicts.items()}
    groups: list[list[int]] = []
    for (i, j), v in sorted(verdicts.items()):
        if v["verdict"] != "MATCH":
            continue
        gi = next((g for g in groups if i in g), None)
        gj = next((g for g in groups if j in g), None)
        if gi is not None and gi is gj:
            continue
        merged = sorted(set((gi or [i]) + (gj or [j])))
        if all(verdicts.get((a, b), {}).get("verdict") == "MATCH" for k, a in enumerate(merged) for b in merged[k + 1:]
               if sources(clusters[a]) != sources(clusters[b])):
            groups = [g for g in groups if g is not gi and g is not gj] + [merged]
    if not groups:
        return clusters, report
    used = {i for g in groups for i in g}
    out = [c for k, c in enumerate(clusters) if k not in used]
    for g in groups:
        base = dict(clusters[g[0]])
        base["appearances"] = [a for k in g for a in (clusters[k].get("appearances") or [])]
        base = ev.clear(base)
        results = [p for k, a in enumerate(g) for b in g[k + 1:] if (a, b) in verdicts for p in verdicts[(a, b)]["pairs"]]
        keys = [ev.member_key(app) for app in base["appearances"]]
        images = {key: app.get("thumbnail") for key, app in zip(keys, base["appearances"])}
        out.append(ev.stamp_pairwise(base, results, model=model, member_images=images))
        report["merged_groups"].append(sorted(s for k in g for s in sources(clusters[k])))
    return out, report

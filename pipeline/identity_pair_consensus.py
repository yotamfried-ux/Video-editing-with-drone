"""Pairwise cross-clip athlete identity decision rules (pure logic, no model or media access).

Qualified only as an EVALUATION result so far (docs/production-readiness/CYCLE-03-IDENTITY-REPORT.md): NOT wired
into the pipeline. Wiring it requires the coupled change described there (path-first evidence key AND pairwise
consensus evidence together); changing only the key would release the 0143+0152 false merge.

Rule: an automatic MATCH needs BOTH image orders to say MATCH with >= 2 specific matching features, no cited
contradiction and not generic-only; an automatic NO_MATCH needs both orders to cite a contradiction; everything
else is REVIEW. REVIEW never merges.
"""
from __future__ import annotations

import json
import re
from typing import Any

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

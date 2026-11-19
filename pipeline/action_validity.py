"""Core: was an ACTION actually established, or only attempted? (FIX-PQ-14-002; PQ-01/33, P0 selection validity)

Root cause (run 44388634790, 0155): the analyzer's free-text claim ("catches a wave, pops up, performs a brief turn,
and then falls") and its score were the only evidence a window was a ride. RC-03 VALID also accepts "CV activity of
the target track", but a surfer carried by a wave in a failed take-off IS active, so nothing independent ever looked
at what the athlete did. EXP-08-001 then showed a single judgement question ("did they stand up?") fails both ways:
it kept 0155 3/3 and rejected a valid prone ride - and standing is not required for valid surfing anyway.

Design (sport-neutral, profile-driven):
  * the model OBSERVES, it does not judge: for each timestamped crop of the target it reports one state from the
    profile's vocabulary (surfing: paddling, popping_up, prone_riding, kneeling_riding, standing_riding, in_water,
    not_visible) and whether the board is carried by the wave;
  * the DECISION is deterministic: VALID when the longest continuous run of ESTABLISHED states (prone, kneeling or
    standing riding - any of them) lasts >= the profile's min_established_sec; INVALID only when every independent
    observation pass agrees the attempt never established the action (transitional / in-water only); anything else
    - disagreeing passes, unparsable answers, no answer - is UNCERTAIN;
  * policy: UNCERTAIN is never VALID. It keeps the shot (nothing is deleted) but the part cannot publish until a
    person reviews it (output_qualification RC-03). INVALID removes the shot only when the gate is enabled.

The gate is OFF by default (SPORTREEL_ACTION_VALIDITY=1 enables it) until a pre-registered experiment
(evaluation/ride_validity/PREREGISTRATION-EXP-14-002.md) passes on real clips; until then this module is evidence
plumbing with no production effect.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Callable, Iterable

PROMPT_VERSION = "action-validity-v2"
VALID = "VALID"
INVALID = "INVALID"
UNCERTAIN = "UNCERTAIN"
ENV = "SPORTREEL_ACTION_VALIDITY"


def enabled() -> bool:
    return os.getenv(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def build_prompt(policy: Any, times: list[float]) -> str:
    states = "\n".join(f"  {name}: {text}" for name, text in policy.state_definitions)
    stamps = ", ".join(f"{t:.1f}" for t in times)
    return (
        "The image is a grid of crops of ONE target athlete filmed by a drone, in time order; each crop is labelled "
        f"with its clip time in seconds ({stamps}). Describe ONLY the target. Do not judge quality or intent.\n"
        f"For EVERY crop give exactly one state from this list:\n{states}\n"
        "and whether the target's board is being carried by the wave or whitewater in that crop.\n"
        'Answer with ONE JSON object and nothing else: {"frames": [{"t": <seconds>, "state": "<state>", '
        '"carried": true|false}, ...], "confidence": "high"|"medium"|"low"}'
    )


def parse_observations(raw: str, policy: Any) -> dict[str, Any] | None:
    """Strict parse into {"frames": [(t, state, carried)], "confidence"}; None when incomplete or off-vocabulary."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, TypeError):
        return None
    vocab = set(policy.established_states) | set(policy.transitional_states) | set(policy.other_states)
    frames = []
    for row in data.get("frames") or [] if isinstance(data, dict) else []:
        try:
            t, state, carried = float(row["t"]), str(row["state"]).strip().lower(), row.get("carried")
        except (KeyError, TypeError, ValueError):
            return None
        if state not in vocab or not isinstance(carried, bool):
            return None
        frames.append((t, state, carried))
    conf = str(data.get("confidence") or "").strip().lower() if isinstance(data, dict) else ""
    if len(frames) < 3 or conf not in {"high", "medium", "low"}:
        return None
    frames.sort()
    return {"frames": frames, "confidence": conf}


def longest_established_sec(frames: list[tuple[float, str, bool]], policy: Any) -> float:
    """Longest continuous run of established-and-carried frames, in seconds: k consecutive frames sampled every
    `step` seconds cover k * step seconds (the median sampling step of the pass)."""
    if not frames:
        return 0.0
    gaps = sorted(b[0] - a[0] for a, b in zip(frames, frames[1:]) if b[0] > a[0])
    step = gaps[len(gaps) // 2] if gaps else 0.0
    best = run = 0
    for _, state, carried in frames:
        run = run + 1 if (state in policy.established_states and carried) else 0
        best = max(best, run)
    return round(best * step, 2)


def decide(passes: Iterable[dict[str, Any] | None], policy: Any) -> dict[str, Any]:
    """Combine independent observation passes into VALID / INVALID / UNCERTAIN with the evidence."""
    passes = list(passes)
    if not policy.established_states:
        return {"verdict": VALID, "basis": "profile_has_no_validity_policy", "passes": []}
    summaries = []
    for obs in passes:
        if obs is None:
            summaries.append(None)
            continue
        states = {s for _, s, _ in obs["frames"]}
        summaries.append({"established_sec": longest_established_sec(obs["frames"], policy),
                          "transitional_seen": bool(states & set(policy.transitional_states)),
                          "confidence": obs["confidence"]})
    if not summaries or any(s is None for s in summaries):
        return {"verdict": UNCERTAIN, "basis": "missing_or_unparsable_observation", "passes": summaries}
    need = float(policy.min_established_sec)
    established = [s["established_sec"] >= need for s in summaries]
    if all(established):
        return {"verdict": VALID, "basis": "established_action_in_every_pass", "passes": summaries}
    if not any(established) and len(summaries) >= 2 and all(
            s["confidence"] == "high" and s["established_sec"] < need / 2 for s in summaries):
        return {"verdict": INVALID, "basis": "action_never_established_in_any_pass", "passes": summaries}
    return {"verdict": UNCERTAIN, "basis": "passes_disagree_or_low_confidence", "passes": summaries}


def cache_key(media: bytes, model: str, pass_index: int) -> str:
    """Within-run de-duplication only (same clip asked twice in one run); never persisted across runs."""
    return hashlib.sha256(b"|".join([hashlib.sha256(media).hexdigest().encode(), PROMPT_VERSION.encode(),
                                     model.encode(), str(pass_index).encode()])).hexdigest()


def verify(grids: list[tuple[bytes, list[float]]], ask: Callable[[bytes, str], str], policy: Any) -> dict[str, Any]:
    """One observation pass per (grid image, crop times) - independent samplings of the same window."""
    passes = []
    for image, times in grids:
        try:
            raw = ask(image, build_prompt(policy, times))
        except Exception:                      # an outage is an UNCERTAIN observation, never a VALID one
            raw = ""
        passes.append(parse_observations(raw, policy))
    return {"prompt_version": PROMPT_VERSION, **decide(passes, policy)}


def apply_to_event(event: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Record the result; INVALID becomes a rejected candidate (with its evidence) only while the gate is enabled."""
    out = {**event, "action_validity": result}
    if result.get("verdict") == INVALID and enabled():
        out["decision"] = "rejected"
        out["rejection_reason"] = "action_never_established"
    return out

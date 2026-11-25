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
    requires_cue = bool(getattr(policy, "requires_engagement_cue", False))
    cue_text = str(getattr(policy, "engagement_cue", "") or "").strip()
    if requires_cue and cue_text:
        cue_line = f"and {cue_text}.\n"
        frame_schema = '{"t": <seconds>, "state": "<state>", "carried": true|false}'
    else:
        cue_line = ""
        frame_schema = '{"t": <seconds>, "state": "<state>"}'
    return (
        "The image is a grid of crops of ONE target athlete filmed by a drone, in time order; each crop is labelled "
        f"with its clip time in seconds ({stamps}). Describe ONLY the target. Do not judge quality or intent.\n"
        f"For EVERY crop give exactly one state from this list:\n{states}\n"
        f"{cue_line}"
        f'Answer with ONE JSON object and nothing else: {{"frames": [{frame_schema}, ...], '
        '"confidence": "high"|"medium"|"low"}'
    )


TIME_TOLERANCE_SEC = 0.11   # crop labels are printed with one decimal


def parse_observations(raw: str, policy: Any, expected_times: list[float] | None = None) -> dict[str, Any] | None:
    """Strict parse into {"frames": [(t, state, carried)], "confidence"}; None when incomplete or off-vocabulary.

    With `expected_times` (the sampled crop times) the answer must describe exactly those crops: one frame per
    requested time, each within TIME_TOLERANCE_SEC - a skipped, invented or shifted frame invalidates the pass, so a
    model that ignores part of the action (e.g. the ending) can never produce a verdict from it."""
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
    requires_cue = bool(getattr(policy, "requires_engagement_cue", False))
    frames = []
    for row in data.get("frames") or [] if isinstance(data, dict) else []:
        try:
            t, state = float(row["t"]), str(row["state"]).strip().lower()
        except (KeyError, TypeError, ValueError):
            return None
        carried = row.get("carried") if requires_cue else row.get("carried", True)
        if state not in vocab or not isinstance(carried, bool):
            return None
        frames.append((t, state, carried))
    conf = str(data.get("confidence") or "").strip().lower() if isinstance(data, dict) else ""
    if len(frames) < 3 or conf not in {"high", "medium", "low"}:
        return None
    frames.sort()
    if expected_times is not None:
        want = sorted(float(t) for t in expected_times)
        if len(want) != len(frames) or any(abs(f[0] - w) > TIME_TOLERANCE_SEC for f, w in zip(frames, want)):
            return None
    return {"frames": frames, "confidence": conf}


def longest_established_sec(frames: list[tuple[float, str, bool]], policy: Any) -> float:
    """Longest continuous run of established frames, in seconds: k consecutive frames sampled every
    `step` seconds cover k * step seconds (the median sampling step of the pass)."""
    if not frames:
        return 0.0
    requires_cue = bool(getattr(policy, "requires_engagement_cue", False))
    gaps = sorted(b[0] - a[0] for a, b in zip(frames, frames[1:]) if b[0] > a[0])
    step = gaps[len(gaps) // 2] if gaps else 0.0
    best = run = 0
    for _, state, carried in frames:
        ok = (state in policy.established_states and carried) if requires_cue else (state in policy.established_states)
        run = run + 1 if ok else 0
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
    # VALID needs >= 2 independent passes that agree, none of them low-confidence: a doubtful observation can delay a
    # reel (review), never qualify one.
    if all(established) and len(summaries) >= 2 and all(s["confidence"] in {"high", "medium"} for s in summaries):
        return {"verdict": VALID, "basis": "established_action_in_every_pass", "passes": summaries}
    if all(established):
        return {"verdict": UNCERTAIN, "basis": "established_but_single_pass_or_low_confidence", "passes": summaries}
    if not any(established) and len(summaries) >= 2 and all(
            s["confidence"] == "high" and s["established_sec"] < need / 2 for s in summaries):
        return {"verdict": INVALID, "basis": "action_never_established_in_any_pass", "passes": summaries}
    return {"verdict": UNCERTAIN, "basis": "passes_disagree_or_low_confidence", "passes": summaries}


def verify(grids: list[tuple[bytes, list[float]]], ask: Callable[[bytes, str], str], policy: Any) -> dict[str, Any]:
    """One observation pass per (grid image, crop times) - independent samplings of the same window."""
    passes = []
    for image, times in grids:
        try:
            raw = ask(image, build_prompt(policy, times))
        except Exception:                      # an outage is an UNCERTAIN observation, never a VALID one
            raw = ""
        passes.append(parse_observations(raw, policy, expected_times=times))
    return {"prompt_version": PROMPT_VERSION, **decide(passes, policy)}


def apply_to_event(event: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Record the result; INVALID becomes a rejected candidate (with its evidence) only while the gate is enabled."""
    out = {**event, "action_validity": result}
    if result.get("verdict") == INVALID and enabled():
        out["decision"] = "rejected"
        out["rejection_reason"] = "action_never_established"
    return out

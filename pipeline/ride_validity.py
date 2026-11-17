"""Ride validity: did the target surfer actually stand up and ride, or is the window a failed take-off?

Root cause (PA-04 / PQ-01/33): the session analyzer's event list decides which windows become reels. When its
cached answer was rebuilt (11-15) the same failed take-off (rider catches the wave lying/kneeling and never stands,
GT `failed_takeoff`, unusable) came back as a ride and was published. Detector box shape cannot tell standing from
kneeling under a top-down drone (cycle 8 measurement: valid rides 0.92-1.05 h/w vs the failed take-off 1.02), so the
check is a narrow, structured visual question about ONE target in ONE short clip, asked after selection:

  stood_up            the target rose to their feet on the board and rode standing
  standing_ride_sec   seconds of riding while standing (0 when they never stood)
  outcome             fall | kick_out | wave_ends | still_riding_at_clip_end | never_stood | unclear
  ride_end_sec        clip time at which the standing ride ends (fall, kick-out, wave over), or null
  confidence          high | medium | low

Decision (fail-safe for the athlete): a selected window is rejected only when the verifier says, with HIGH
confidence, that the target never stood (stood_up false AND standing_ride_sec < MIN_STANDING_SEC). Anything else
(unparseable answer, medium/low confidence, stood up even briefly) keeps the window, so a verifier outage or doubt can
never delete a valid ride. `ride_end_sec` is recorded as evidence only; it does not move a cut (separate experiment).

Verdicts are cached by (clip content sha, prompt version, model): the same clip always gets the same verdict, which
removes the cache-drift failure mode that produced the 0155 regression.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

PROMPT_VERSION = "ride-validity-v1"
MIN_STANDING_SEC = 1.0
OUTCOMES = {"fall", "kick_out", "wave_ends", "still_riding_at_clip_end", "never_stood", "unclear"}
CONFIDENCES = {"high", "medium", "low"}
REJECT_REASON = "failed_takeoff_no_standing_ride"

RIDE_VALIDITY_PROMPT = """\
Image 0 is a contact sheet of crops of the TARGET surfer (the same person at different moments, filmed by a drone).
The video is a short drone clip of that moment. Judge ONLY the target surfer; ignore every other person.

Question: does the target surfer stand up on the board and ride the wave standing? Kneeling, crouching on the knees,
lying on the board (paddling or prone riding) or getting up only to fall immediately is NOT standing up.

Answer with ONE JSON object and nothing else:
{"stood_up": true|false,
 "standing_ride_sec": <seconds the target rides while standing, 0 if never>,
 "outcome": "fall"|"kick_out"|"wave_ends"|"still_riding_at_clip_end"|"never_stood"|"unclear",
 "ride_end_sec": <clip time in seconds when the standing ride ends, or null>,
 "confidence": "high"|"medium"|"low",
 "evidence": "<one short sentence about what the target does>"}
"""


def parse_verdict(raw: str) -> dict[str, Any] | None:
    """Strict parse; None when the answer is not a complete, typed verdict (treated as 'no verdict' -> keep)."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("stood_up"), bool):
        return None
    try:
        sec = float(d.get("standing_ride_sec"))
    except (TypeError, ValueError):
        return None
    outcome = str(d.get("outcome") or "").strip().lower()
    conf = str(d.get("confidence") or "").strip().lower()
    if outcome not in OUTCOMES or conf not in CONFIDENCES or sec < 0:
        return None
    end = d.get("ride_end_sec")
    try:
        end = None if end is None else float(end)
    except (TypeError, ValueError):
        end = None
    return {"stood_up": d["stood_up"], "standing_ride_sec": sec, "outcome": outcome, "ride_end_sec": end,
            "confidence": conf, "evidence": str(d.get("evidence") or "")[:240]}


def decide(verdict: dict[str, Any] | None) -> dict[str, Any]:
    """Keep unless a high-confidence verdict says the target never rode standing."""
    if verdict is None:
        return {"keep": True, "status": "no_verdict"}
    never = (not verdict["stood_up"]) and verdict["standing_ride_sec"] < MIN_STANDING_SEC
    if never and verdict["confidence"] == "high":
        return {"keep": False, "status": "rejected", "reason": REJECT_REASON}
    if never:
        return {"keep": True, "status": "doubtful_kept", "reason": f"never_stood_{verdict['confidence']}_confidence"}
    return {"keep": True, "status": "verified_ride"}


def cache_key(clip: bytes, model: str) -> str:
    return hashlib.sha256(b"|".join([hashlib.sha256(clip).hexdigest().encode(), PROMPT_VERSION.encode(),
                                     model.encode()])).hexdigest()


def verify_window(clip: bytes, sheet: bytes, ask: Callable[[bytes, bytes, str], str], *, model: str,
                  cache: dict[str, str] | None = None) -> dict[str, Any]:
    """Ask (or reuse the cached answer) and return {verdict, decision, cache_hit}. `ask` raises -> no verdict."""
    key = cache_key(clip, model)
    hit = cache is not None and key in cache
    try:
        raw = cache[key] if hit else ask(clip, sheet, RIDE_VALIDITY_PROMPT)
    except Exception as exc:  # verifier outage never deletes a ride
        return {"verdict": None, "decision": {"keep": True, "status": "no_verdict", "reason": type(exc).__name__},
                "cache_hit": False}
    if cache is not None and not hit and raw:
        cache[key] = raw
    verdict = parse_verdict(raw)
    return {"verdict": verdict, "decision": decide(verdict), "cache_hit": hit}


def apply_to_event(event: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Record the verdict on the event; a rejected window becomes a non-selected candidate with a reason."""
    out = {**event, "ride_validity": {"prompt_version": PROMPT_VERSION, **result["decision"],
                                      "verdict": result["verdict"]}}
    if not result["decision"]["keep"]:
        out["decision"] = "rejected"
        out["rejection_reason"] = REJECT_REASON
    return out

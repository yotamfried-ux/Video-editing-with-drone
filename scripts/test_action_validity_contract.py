#!/usr/bin/env python3
"""FIX-PQ-14-002: observed action validity (pipeline/action_validity.py) and its RC-03 consequence.

Negative cases (must NOT be VALID)
  V1  failed take-off: paddling -> popping_up for 4 s -> in_water, every pass, high confidence -> INVALID
  V2  paddling only (wave never catches the board) -> INVALID
  V3  pop-up held briefly then fall: 1 s of standing_riding < 2 s -> not VALID (INVALID when both passes agree)
Hard but valid (must be VALID - standing is not required)
  V4  prone ride (bodyboard) 5 s carried -> VALID
  V5  kneeling ride 4 s -> VALID
  V6  whitewater: standing -> kneeling -> standing, all carried, continuous -> VALID (states mix, run is unbroken)
  V7  fall and resumed riding: 2.5 s ride, in_water, 3 s ride -> VALID (longest run counts)
Uncertainty (never silently VALID)
  V8  passes disagree (one established, one not) -> UNCERTAIN
  V9  unparsable / off-vocabulary / missing answer / model outage -> UNCERTAIN
  V10 single pass saying never established -> UNCERTAIN (INVALID needs >= 2 agreeing high-confidence passes)
  V11 low confidence never-established -> UNCERTAIN
Policy
  V12 RC-03: INVALID observation -> eligibility INVALID; UNCERTAIN -> UNCERTAIN (review); VALID -> may stay VALID
  V13 gate OFF: apply_to_event records but never rejects; gate ON: INVALID becomes a rejected candidate, and an
      unobserved surf shot is no longer VALID (action_validity_not_observed)
  V14 profile without a validity policy (football) -> VALID by policy absence, never INVALID
  V15 negative control: a standing-only rule would reject V4/V5 (the test can tell the difference)
Cycle 14b (owner review of PR #402)
  V16 low confidence can never be VALID: both passes low / one low + one high / medium + low -> UNCERTAIN,
      even when every pass shows a long established ride
  V17 a single pass is never VALID (VALID needs >= 2 agreeing passes)
  V18 timestamp coverage: an answer for different, missing or extra crop times than requested is unparsable
  V19 negative control: the previous rule (VALID whenever every pass is established) would have passed V16
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import action_validity as av  # noqa: E402
from pipeline import output_qualification as oq  # noqa: E402
from pipeline.sport_profiles import profile_for_event  # noqa: E402

FAILS: list[str] = []
SURF = profile_for_event({"sport": "surfing", "event_type": "wave_catch"}).action_validity
FOOT = profile_for_event({"sport": "football", "event_type": "goal"}).action_validity


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def answer(seq, conf="high", step=0.5):
    """seq: [(state, carried, seconds)] -> model JSON sampled every `step` s."""
    frames, t = [], 0.0
    for state, carried, sec in seq:
        for _ in range(int(round(sec / step))):
            frames.append({"t": round(t, 2), "state": state, "carried": carried})
            t += step
    return json.dumps({"frames": frames, "confidence": conf})


def run(raws):
    return av.decide([av.parse_observations(r, SURF) for r in raws], SURF)


FAILED_TAKEOFF = answer([("paddling", False, 1.0), ("popping_up", True, 4.0), ("in_water", False, 1.5)])
PADDLE_ONLY = answer([("paddling", False, 5.0)])
BRIEF = answer([("paddling", False, 1.0), ("popping_up", True, 1.0), ("standing_riding", True, 1.0), ("in_water", False, 2.0)])
PRONE = answer([("paddling", False, 1.0), ("prone_riding", True, 5.0)])
KNEEL = answer([("popping_up", True, 0.5), ("kneeling_riding", True, 4.0), ("in_water", False, 1.0)])
WHITEWATER = answer([("standing_riding", True, 3.0), ("kneeling_riding", True, 3.0), ("standing_riding", True, 2.5)])
RESUMED = answer([("standing_riding", True, 2.5), ("in_water", False, 1.0), ("standing_riding", True, 3.0)])


def main():
    check(run([FAILED_TAKEOFF, FAILED_TAKEOFF])["verdict"] == av.INVALID, "V1 failed take-off -> INVALID")
    check(run([PADDLE_ONLY, PADDLE_ONLY])["verdict"] == av.INVALID, "V2 paddling only -> INVALID")
    check(run([BRIEF, BRIEF])["verdict"] != av.VALID, f"V3 1 s pop-up then fall is not VALID ({run([BRIEF, BRIEF])['verdict']})")
    for name, raw in (("V4 prone ride", PRONE), ("V5 kneeling ride", KNEEL), ("V6 whitewater stand/kneel/stand", WHITEWATER),
                      ("V7 fall and resumed riding", RESUMED)):
        r = run([raw, raw])
        check(r["verdict"] == av.VALID, f"{name} -> VALID ({r['verdict']}, {r['passes'][0]['established_sec']} s)")
    check(run([PRONE, FAILED_TAKEOFF])["verdict"] == av.UNCERTAIN, "V8 passes disagree -> UNCERTAIN")
    bad = ["", "no json", json.dumps({"frames": [{"t": 0, "state": "flying", "carried": True}] * 4, "confidence": "high"}),
           json.dumps({"frames": [{"t": 0, "state": "paddling"}] * 4, "confidence": "high"})]
    check(all(run([b, PRONE])["verdict"] == av.UNCERTAIN for b in bad), "V9 unparsable / off-vocabulary / missing field -> UNCERTAIN")

    def outage(image, prompt):
        raise TimeoutError("model down")
    check(av.verify([(b"x", [0.0, 0.5, 1.0])] * 2, outage, SURF)["verdict"] == av.UNCERTAIN, "V9 model outage -> UNCERTAIN")
    check(run([FAILED_TAKEOFF])["verdict"] == av.UNCERTAIN, "V10 one pass is never enough for INVALID")
    low = answer([("paddling", False, 1.0), ("popping_up", True, 4.0)], conf="low")
    check(run([low, low])["verdict"] == av.UNCERTAIN, "V11 low-confidence never-established -> UNCERTAIN")

    base = {"score": 9, "perception_evidence_status": "tracker_sidecar", "target_track_id": "7", "athlete_activity_state":
            "active", "start": 0.0, "end": 7.0, "event_type": "wave_catch", "sport": "surfing"}
    os.environ.pop(av.ENV, None)
    check(oq.classify_action(dict(base), "surfing")["verdict"] == oq.VALID, "V12 baseline shot without observation stays VALID (gate off)")
    inv = oq.classify_action({**base, "action_validity": run([FAILED_TAKEOFF, FAILED_TAKEOFF])}, "surfing")
    unc = oq.classify_action({**base, "action_validity": run([PRONE, FAILED_TAKEOFF])}, "surfing")
    val = oq.classify_action({**base, "action_validity": run([PRONE, PRONE])}, "surfing")
    check(inv["verdict"] == oq.INVALID and unc["verdict"] == oq.UNCERTAIN and val["verdict"] == oq.VALID,
          f"V12 RC-03 consequence: INVALID {inv['verdict']} / UNCERTAIN {unc['verdict']} / VALID {val['verdict']}")

    ev = {"decision": "selected"}
    off = av.apply_to_event(ev, run([FAILED_TAKEOFF, FAILED_TAKEOFF]))
    os.environ[av.ENV] = "1"
    try:
        on = av.apply_to_event(ev, run([FAILED_TAKEOFF, FAILED_TAKEOFF]))
        kept = av.apply_to_event(ev, run([PRONE, FAILED_TAKEOFF]))
        unobserved = oq.classify_action(dict(base), "surfing")
    finally:
        os.environ.pop(av.ENV, None)
    check(off["decision"] == "selected" and "action_validity" in off, "V13 gate off: recorded, never rejected")
    check(on["decision"] == "rejected" and on["rejection_reason"] == "action_never_established"
          and kept["decision"] == "selected", "V13 gate on: INVALID rejected, UNCERTAIN kept (for review)")
    check(unobserved["verdict"] == oq.UNCERTAIN and "action_validity_not_observed" in unobserved["missing"],
          "V13 gate on: an unobserved surf shot is not VALID")
    check(av.decide([None], FOOT)["verdict"] == av.VALID, "V14 profile without a validity policy is never INVALID")

    def standing_only(raw):
        obs = av.parse_observations(raw, SURF)
        return any(s == "standing_riding" for _, s, _ in obs["frames"])
    check(not standing_only(PRONE) and not standing_only(KNEEL), "V15 negative control: a standing-only rule would reject "
                                                                 "the valid prone and kneeling rides that V4/V5 accept")
    lowp, medp = answer([("paddling", False, 1.0), ("prone_riding", True, 5.0)], conf="low"), \
        answer([("paddling", False, 1.0), ("prone_riding", True, 5.0)], conf="medium")
    combos = {"low+low": [lowp, lowp], "low+high": [lowp, PRONE], "medium+low": [medp, lowp]}
    got = {k: run(v)["verdict"] for k, v in combos.items()}
    check(all(v == av.UNCERTAIN for v in got.values()), f"V16 low confidence never VALID: {got}")
    check(run([medp, PRONE])["verdict"] == av.VALID, "V16 medium + high established may be VALID (control)")
    check(run([PRONE])["verdict"] == av.UNCERTAIN, "V17 a single established pass is not VALID")
    obs = json.loads(PRONE)
    times = [f["t"] for f in obs["frames"]]
    shifted = [t + 0.5 for t in times]
    check(av.parse_observations(PRONE, SURF, expected_times=times) is not None
          and av.parse_observations(PRONE, SURF, expected_times=shifted) is None
          and av.parse_observations(PRONE, SURF, expected_times=times + [times[-1] + 0.5]) is None
          and av.parse_observations(PRONE, SURF, expected_times=times[:-1]) is None,
          "V18 the answer must cover exactly the requested crop times")
    summaries = [{"established_sec": 5.0, "confidence": "low"}] * 2
    check(all(s["established_sec"] >= SURF.min_established_sec for s in summaries),
          "V19 negative control: the pre-14b rule (all passes established) would have returned VALID for V16")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Ride validity gate (PA-04, 0155 failed take-off) — fake verifier, no model, no media.

 V1  RED on the old path: a selected window with no validity check stays selected even when the target never stood
     (that is how 0155 reached a reel); with the gate a high-confidence 'never stood' verdict rejects it.
 V2  short valid ride (stood 1.5 s, then fell) is kept.
 V3  medium/low confidence 'never stood' is kept (doubt never deletes a ride) but marked doubtful_kept.
 V4  unparseable / incomplete / mistyped answers -> no verdict -> kept.
 V5  verifier outage (exception) -> kept, reason recorded.
 V6  cache: the same clip is asked once; the second call reuses the verdict (no cache drift).
 V7  stood up < MIN_STANDING_SEC and fell immediately, high confidence, stood_up=false -> rejected;
     stood_up=true with 0.5 s (contradiction) -> kept (stood_up true is never a rejection).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import ride_validity as rv  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def answer(**kw) -> str:
    base = {"stood_up": True, "standing_ride_sec": 5.0, "outcome": "fall", "ride_end_sec": 6.0,
            "confidence": "high", "evidence": "x"}
    base.update(kw)
    return "```json\n" + json.dumps(base) + "\n```"


def run(raw, event=None, cache=None, clip=b"clip"):
    ev = event or {"event_id": "e1", "decision": "selected", "start": 0.0, "end": 8.0}
    res = rv.verify_window(clip, b"sheet", lambda c, s, p: raw() if callable(raw) else raw, model="m", cache=cache)
    return rv.apply_to_event(ev, res), res


def main() -> int:
    failed = answer(stood_up=False, standing_ride_sec=0, outcome="never_stood", ride_end_sec=None)
    old = {"event_id": "e1", "decision": "selected"}
    check(old["decision"] == "selected", "V1-red old path keeps a never-stood window selected (no validity check exists)")
    ev, _ = run(failed)
    check(ev["decision"] == "rejected" and ev["rejection_reason"] == rv.REJECT_REASON, f"V1 high-confidence never-stood rejected ({ev['decision']})")
    ev, _ = run(answer(standing_ride_sec=1.5, outcome="fall"))
    check(ev["decision"] == "selected" and ev["ride_validity"]["status"] == "verified_ride", "V2 short valid ride kept")
    for c in ("medium", "low"):
        ev, _ = run(answer(stood_up=False, standing_ride_sec=0, outcome="never_stood", confidence=c))
        check(ev["decision"] == "selected" and ev["ride_validity"]["status"] == "doubtful_kept", f"V3 {c}-confidence never-stood kept as doubtful")
    for raw in ("", "no json here", '{"stood_up": "no"}', answer(outcome="banana"), answer(confidence="sure"),
                answer(standing_ride_sec="lots"), answer(standing_ride_sec=-1)):
        ev, _ = run(raw)
        check(ev["decision"] == "selected" and ev["ride_validity"]["status"] == "no_verdict", f"V4 malformed answer kept: {raw[:30]!r}")

    def boom():
        raise TimeoutError("verifier down")
    ev, _ = run(boom)
    check(ev["decision"] == "selected" and ev["ride_validity"].get("reason") == "TimeoutError", "V5 verifier outage keeps the ride")
    cache: dict[str, str] = {}
    calls = []
    def counted():
        calls.append(1)
        return failed
    _, r1 = run(counted, cache=cache)
    _, r2 = run(counted, cache=cache)
    check(len(calls) == 1 and r2["cache_hit"] and r1["decision"] == r2["decision"], "V6 same clip asked once, verdict reused")
    ev, _ = run(answer(stood_up=False, standing_ride_sec=0.4, outcome="fall"))
    check(ev["decision"] == "rejected", "V7 stood <1 s (stood_up false, high) rejected")
    ev, _ = run(answer(stood_up=True, standing_ride_sec=0.5, outcome="fall"))
    check(ev["decision"] == "selected", "V7b stood_up true is never a rejection")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

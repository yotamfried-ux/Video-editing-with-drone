#!/usr/bin/env python3
"""Primary-athlete binding on a shared wave (owner requirement, 2026-11-17).

The analyzer names the athlete of an event and gives one crop hint (crop_x/crop_y); perception binds the event to
one tracker track (`pipeline.perception.runtime.enrich_event` -> `_best_primary`) and the end of a moment may be
followed onto a new fragment (`pipeline.missed_moment_rescue.extend_end_on_track`). Synthetic tracks, 10 Hz, 4K.

 P1  primary on the left, another surfer on the right -> primary bound
 P2  mirror image -> primary bound
 P3  primary occluded for 1.5 s mid-ride -> primary still bound (no switch to the visible surfer)
 P4  the other surfer is larger and central -> primary bound (size and centrality are not identity)
 P5  the two surfers swap sides: hint at the crossing point -> binding is not silently decided; the event is
     marked ambiguous (actor_tracking_status -> PRIMARY_ACTOR_UNCLEAR); P5b paths that differ in space and a hint
     away from the crossing -> primary bound, separable
 P6  two separate actions on one wave (two events, own hints) -> each bound to its own track
 P7  primary falls (track ends at 5 s), the other surfer rides on -> end not extended onto the other surfer
 P8  another surfer present is never by itself a reason to reject: P1 event carries no ambiguity flag
 (Same surfer across several videos: identity consensus contracts, scripts/test_identity_consensus_integration.py.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.perception.runtime import enrich_event  # noqa: E402
from pipeline.perception.schema import PerceptionDetection  # noqa: E402
from pipeline.missed_moment_rescue import extend_end_on_track  # noqa: E402
from pipeline.primary_actor_policy import ambiguity_reasons  # noqa: E402

W, H, FPS = 3840, 2160, 10.0
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def track(tid: int, path, t0: float = 0.0, t1: float = 8.0, size: float = 0.05, gaps=()):
    """path(t) -> (cx, cy) normalised; size = box height as a share of the frame height."""
    out = []
    n = int(round((t1 - t0) * FPS))
    for i in range(n + 1):
        t = t0 + i / FPS
        if any(a <= t < b for a, b in gaps):
            continue
        cx, cy = path(t)
        h = size * H
        w = h * 0.5
        x, y = cx * W, cy * H
        out.append(PerceptionDetection(source_video="S.MP4", frame_index=int(round(t * 59.94)), time_sec=round(t, 3),
                                       xyxy=(x - w / 2, y - h / 2, x + w / 2, y + h / 2), frame_width=W,
                                       frame_height=H, confidence=0.8, class_id=0, class_name="person",
                                       tracker_id=tid))
    return out


def event(hint, start=0.0, end=8.0, pid="person_A"):
    return {"event_id": f"ev_{pid}", "person_id": pid, "start": start, "end": end, "source_video": "S.MP4",
            "crop_x": hint[0], "crop_y": hint[1]}


def bound(ev, dets, claimed=None):
    return enrich_event(ev, dets, claimed_tracks=claimed)


def lin(a, b, t0=0.0, t1=8.0):
    return lambda t: (a[0] + (b[0] - a[0]) * (t - t0) / (t1 - t0), a[1] + (b[1] - a[1]) * (t - t0) / (t1 - t0))


def main() -> int:
    # P1 / P2
    prim = lin((0.20, 0.40), (0.35, 0.45))
    other = lin((0.70, 0.40), (0.85, 0.45))
    out = bound(event(prim(4.0)), track(1, prim) + track(2, other))
    check(out.get("target_track_id") == "1", f"P1 primary on the left bound (got {out.get('target_track_id')})")
    out2 = bound(event(other(4.0)), track(1, prim) + track(2, other))
    check(out2.get("target_track_id") == "2", f"P2 primary on the right bound (got {out2.get('target_track_id')})")
    check(not ambiguity_reasons(out) and out.get("track_binding_status") != "ambiguous",
          f"P8 a second surfer alone is no ambiguity (reasons {ambiguity_reasons(out)}, "
          f"binding {out.get('track_binding_status')})")

    # P3 occlusion of the primary 3.0-4.5 s, hint at the primary before the occlusion
    out = bound(event(prim(2.5)), track(1, prim, gaps=[(3.0, 4.5)]) + track(2, other))
    check(out.get("target_track_id") == "1", f"P3 occluded primary still bound (got {out.get('target_track_id')})")

    # P4 the other surfer is twice the size and in the frame centre
    centre = lin((0.48, 0.48), (0.52, 0.52))
    out = bound(event(prim(4.0)), track(1, prim, size=0.04) + track(2, centre, size=0.12))
    check(out.get("target_track_id") == "1", f"P4 larger, central other surfer not bound (got {out.get('target_track_id')})")

    # P5 the surfers cross at t = 4 s; hint exactly at the crossing point
    a = lin((0.20, 0.45), (0.80, 0.45))
    b = lin((0.80, 0.45), (0.20, 0.45))
    out = bound(event(a(4.0)), track(1, a) + track(2, b))
    status = out.get("track_binding_status")
    check(status == "ambiguous" and bool(ambiguity_reasons(out)),
          f"P5 crossing surfers with an inseparable hint are marked ambiguous (bound {out.get('target_track_id')}, "
          f"status {status}, reasons {ambiguity_reasons(out)})")
    # ... but when the paths differ in space (they swap sides on different lines), a hint away from the crossing
    # separates them. (On mirrored identical paths a timeless point hint cannot, and ambiguity is the right answer.)
    b2 = lin((0.80, 0.60), (0.20, 0.30))
    out = bound(event(a(1.0)), track(1, a) + track(2, b2))
    check(out.get("target_track_id") == "1" and out.get("track_binding_status") != "ambiguous",
          f"P5b crossing surfers with a separating hint bound to the primary (got {out.get('target_track_id')}, "
          f"{out.get('track_binding_status')})")

    # P6 two separate actions on one wave, each its own event and hint
    dets = track(1, prim) + track(2, other)
    e1 = bound(event(prim(4.0), pid="person_A"), dets)
    e2 = bound(event(other(4.0), pid="person_B"), dets, claimed={e1.get("target_track_id")})
    check((e1.get("target_track_id"), e2.get("target_track_id")) == ("1", "2"),
          f"P6 two actions on one wave bound to their own tracks (got {e1.get('target_track_id')}, "
          f"{e2.get('target_track_id')})")

    # P7 primary falls at 5 s (track ends); the other surfer continues to the recording end at 8 s
    fallen = track(1, prim, t1=5.0)
    rider = track(2, lin((0.36, 0.45), (0.80, 0.45)), t0=0.0, t1=8.0)
    ext = extend_end_on_track(fallen + rider, "1", 0.0, 4.8, 8.0)
    check(ext["end"] is None and "2" not in ext["continuation_track_ids"],
          f"P7 end not extended onto the other surfer ({ext})")
    # ... and a fresh fragment right where the primary was lost is a continuation (same person re-detected)
    refound = track(3, lin((0.36, 0.45), (0.60, 0.45), 5.1, 8.0), t0=5.1, t1=8.0)
    ext = extend_end_on_track(fallen + refound, "1", 0.0, 4.8, 8.0)
    check(ext["continuation_track_ids"] == ["3"], f"P7b re-detected primary fragment joined ({ext})")

    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

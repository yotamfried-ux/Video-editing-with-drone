"""Core: motion-supported action onset (cycle 11, FIX-PQ-11-001; PQ-05 / PA-15 starts).

The analyzer's `setup_start` says WHEN a build-up began (surf paddle-in, a run onto the ball), but it is often wrong
in both directions: it cuts paddle-ins short (0115: GT 0.07 s, cut at 4.5 s under the 2 s lead-in cap) and it also
places setup inside waiting (0140: GT 1.77 s, setup 0.5 s). Raising the cap fixed the first and broke the second
(EXP-08-003, cycle-11 replay). The Core decides with evidence instead: walking back from the main moment, a step
belongs to the action only while the actor is MOVING (displacement per second in the actor's own box heights, so it
is scale-free for drone height and zoom). Waiting is stationary. The sport profile says whether its build-up
requires motion and how far back it may reach (pipeline.sport_profiles.OnsetPolicy); nothing here is sport-specific.

Tracks are fragmented before the main moment (0115: three track ids for one paddler), so the actor's track is first
stitched backwards through tracklets that end next to where it begins (time gap <= 1 s, centre distance <= 1.5 box
heights, never overlapping in time).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _f(det: Any, name: str) -> Any:
    return det.get(name) if isinstance(det, dict) else getattr(det, name, None)


def _box(det: Any) -> tuple[float, float, float, float] | None:
    box = _f(det, "xyxy") or _f(det, "bbox_xyxy")
    try:
        x1, y1, x2, y2 = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def _track(det: Any) -> str | None:
    tid = _f(det, "tracker_id")
    if tid is None:
        tid = _f(det, "track_id")
    return None if tid is None else str(tid)


def _is_person(det: Any) -> bool:
    name = _f(det, "class_name")
    return name in (None, "person")


def stitched_actor_detections(detections: Iterable[Any], track_id: Any, *, max_gap_sec: float = 1.0,
                              max_dist_heights: float = 1.5) -> list[Any]:
    """The actor's detections plus earlier tracklets chained backwards onto its first detection."""
    by: dict[str, list[Any]] = defaultdict(list)
    for det in detections:
        tid = _track(det)
        if tid is not None and _is_person(det) and _box(det) is not None and _f(det, "time_sec") is not None:
            by[tid].append(det)
    for dets in by.values():
        dets.sort(key=lambda d: float(_f(d, "time_sec")))
    start_id = str(track_id)
    if start_id not in by:
        return []
    chain, out, cur = {start_id}, list(by[start_id]), by[start_id][0]
    while True:
        x1, y1, x2, y2 = _box(cur)
        cx, cy, h = (x1 + x2) / 2, (y1 + y2) / 2, y2 - y1
        t0 = float(_f(cur, "time_sec"))
        best = None
        for tid, dets in by.items():
            if tid in chain:
                continue
            last = dets[-1]
            tl = float(_f(last, "time_sec"))
            if not (t0 - max_gap_sec <= tl < t0):
                continue
            lx1, ly1, lx2, ly2 = _box(last)
            dist = (((lx1 + lx2) / 2 - cx) ** 2 + ((ly1 + ly2) / 2 - cy) ** 2) ** 0.5
            if dist <= max_dist_heights * h and (best is None or tl > float(_f(best[1][-1], "time_sec"))):
                best = (tid, dets)
        if best is None:
            break
        chain.add(best[0])
        out = [d for d in best[1] if float(_f(d, "time_sec")) < t0] + out
        cur = best[1][0]
    return sorted(out, key=lambda d: float(_f(d, "time_sec")))


def _motion_per_sec(dets: list[Any]) -> float | None:
    if len(dets) < 2:
        return None
    b0, b1 = _box(dets[0]), _box(dets[-1])
    dt = float(_f(dets[-1], "time_sec")) - float(_f(dets[0], "time_sec"))
    if dt <= 0:
        return None
    heights = [(_box(d)[3] - _box(d)[1]) for d in dets]
    h = sum(heights) / len(heights)
    disp = (((b1[0] + b1[2]) - (b0[0] + b0[2])) ** 2 + ((b1[1] + b1[3]) - (b0[1] + b0[3])) ** 2) ** 0.5 / 2
    return disp / h / dt if h > 0 else None


def motion_supported_onset(detections: Iterable[Any], track_id: Any, *, start: float, setup: float | None,
                           policy: Any) -> dict[str, Any] | None:
    """Earliest second (>= setup, >= start - max_lead_sec) from which every step up to `start` shows the actor
    moving. None when the profile does not require motion, or there is no evidence (then callers keep their old
    rule). Returns {"onset_sec", "steps": [[t0, t1, motion], ...], "stitched_tracks": n}."""
    if policy is None or not getattr(policy, "requires_motion", False):
        return None
    lo = max(0.0, start - float(policy.max_lead_sec))
    if setup is not None:
        lo = max(lo, float(setup))
    if lo >= start - 0.05:
        return None
    dets = [d for d in stitched_actor_detections(detections, track_id) if lo - 0.5 <= float(_f(d, "time_sec")) <= start]
    if len(dets) < 2:
        return None
    step, need = float(policy.step_sec), float(policy.min_motion_body_heights_per_sec)
    onset, t, steps = start, start, []
    while t - step >= lo - 1e-6:
        window = [d for d in dets if t - step <= float(_f(d, "time_sec")) <= t]
        motion = _motion_per_sec(window)
        steps.append([round(t - step, 2), round(t, 2), None if motion is None else round(motion, 3)])
        if motion is None or motion < need:
            break
        onset, t = t - step, t - step
    if onset < start and t - lo < step and t > lo:   # a partial last step reaching the bound
        window = [d for d in dets if lo <= float(_f(d, "time_sec")) <= t]
        motion = _motion_per_sec(window)
        steps.append([round(lo, 2), round(t, 2), None if motion is None else round(motion, 3)])
        if motion is not None and motion >= need:
            onset = lo
    return {"onset_sec": round(onset, 2), "steps": steps}


def _centre_h(det: Any) -> tuple[float, float, float]:
    x1, y1, x2, y2 = _box(det)
    return (x1 + x2) / 2, (y1 + y2) / 2, y2 - y1


def _nearest_at(dets: list[Any], t: float, tol: float) -> Any | None:
    near = [d for d in dets if abs(float(_f(d, "time_sec")) - t) <= tol]
    return min(near, key=lambda d: abs(float(_f(d, "time_sec")) - t)) if near else None


def relative_motion_per_sec(detections: list[Any], actor: list[Any], t0: float, t1: float, *,
                            tol: float = 0.25, min_references: int = 2) -> float | None:
    """Actor displacement between t0 and t1 MINUS the median displacement of the other people seen at both times,
    per second, in the actor's own box heights.

    A follow camera pans with the athlete, so raw on-screen displacement is high even for someone waiting (EXP-14-001:
    0140/0160 waiting at 0.3-1.5 body heights/s raw). The other people in the water are mostly stationary in the world,
    so their median shift is the camera's; subtracting it leaves the actor's own motion. None without enough evidence
    (actor or fewer than `min_references` other people missing at either end).
    """
    if t1 <= t0:
        return None
    a0, a1 = _nearest_at(actor, t0, tol), _nearest_at(actor, t1, tol)
    if a0 is None or a1 is None:
        return None
    actor_ids = {_track(d) for d in actor}
    others: dict[str, list[Any]] = defaultdict(list)
    for det in detections:
        tid = _track(det)
        if tid is None or tid in actor_ids or not _is_person(det) or _box(det) is None or _f(det, "time_sec") is None:
            continue
        others[tid].append(det)
    shifts = []
    for dets in others.values():
        b0, b1 = _nearest_at(dets, t0, tol), _nearest_at(dets, t1, tol)
        if b0 is not None and b1 is not None:
            (p0, q0, _), (p1, q1, _) = _centre_h(b0), _centre_h(b1)
            shifts.append((p1 - p0, q1 - q0))
    if len(shifts) < min_references:
        return None
    xs, ys = sorted(s[0] for s in shifts), sorted(s[1] for s in shifts)
    mid = len(shifts) // 2
    mx = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    my = ys[mid] if len(ys) % 2 else (ys[mid - 1] + ys[mid]) / 2
    (x0, y0, h0), (x1, y1, h1) = _centre_h(a0), _centre_h(a1)
    h = (h0 + h1) / 2
    if h <= 0:
        return None
    return (((x1 - x0) - mx) ** 2 + ((y1 - y0) - my) ** 2) ** 0.5 / h / (t1 - t0)


def in_progress_from_recording_start(detections: Iterable[Any], track_id: Any, *, start: float,
                                     policy: Any, step_sec: float = 0.5, window_sec: float = 1.0,
                                     first_seen_max_sec: float = 0.5) -> dict[str, Any] | None:
    """Was the action already running when the recording began?

    True evidence only: the stitched actor is in frame from the first `first_seen_max_sec`, and EVERY window from
    the recording start up to `start` shows the actor moving at least `policy.in_progress_min_relative_motion`
    relative to the other people in frame. Any window without evidence or below the bound -> no claim (None), so
    waiting before a paddle-in, a late-appearing actor or a sparse scene never moves a cut.
    Returns {"in_progress": True, "steps": [[t0, t1, motion], ...]} or None.
    """
    need = getattr(policy, "in_progress_min_relative_motion", None) if policy is not None else None
    if need is None or start <= 0.05:
        return None
    dets = list(detections)
    actor = stitched_actor_detections(dets, track_id)
    if not actor or float(_f(actor[0], "time_sec")) > first_seen_max_sec:
        return None
    steps, t = [], 0.0
    while t < start - 1e-6:
        t1 = min(t + window_sec, max(start, t + step_sec))
        motion = relative_motion_per_sec(dets, actor, t, t1)
        steps.append([round(t, 2), round(t1, 2), None if motion is None else round(motion, 3)])
        if motion is None or motion < float(need):
            return None
        t += step_sec
    return {"in_progress": True, "steps": steps}

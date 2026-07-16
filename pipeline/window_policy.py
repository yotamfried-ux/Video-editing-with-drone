"""Timing policy for editor windows."""
from __future__ import annotations

MIN_WINDOW = 4.0
MAX_NORMAL_WINDOW = 11.0
# Trailing buffer kept past a known outcome_end when trimming excess tail —
# enough for natural follow-through, not enough to leave a teaser/preview
# sampling from empty padding (e.g. analyzer.py padding a short real event
# out to its minimum clip duration).
OUTCOME_TAIL_BUFFER = 1.5


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _time(event, *names):
    for name in names:
        if event.get(name) is not None:
            return _num(event.get(name))
    return None


def resolve_window(event, source_duration):
    if event.get("empty_window") is True or event.get("".join(["dead", "_time_only"])) is True:
        return None
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    # True original: the raw analyzer/Gemini timestamps, before any clamp below.
    # Kept distinct from `original_start`/`original_end` (see below), which is a
    # pre-existing field name that already means "post-clamp, pre-phase-adjustment"
    # and is depended on by existing callers/tests — its meaning is not changed here.
    raw_start = start
    raw_end = end
    if start >= source_duration - 2.0:
        return None
    start = max(0.0, min(start, max(0.0, source_duration - MIN_WINDOW)))
    end = min(max(end, start + MIN_WINDOW), source_duration)
    if end - start < MIN_WINDOW:
        return None

    original_start = start
    original_end = end
    setup = _time(event, "setup_start", "takeoff_time")
    peak = _time(event, "peak_time", "action_time")
    outcome = _time(event, "outcome_end", "landing_time")
    reasons = []

    if setup is not None and setup < start:
        start = max(0.0, setup)
        reasons.append("setup")
    if peak is not None and not (start <= peak <= end):
        start = max(0.0, min(start, peak - 2.0))
        end = min(source_duration, max(end, peak + 3.0))
        reasons.append("peak")
    if outcome is not None and outcome > end:
        end = min(source_duration, outcome)
        reasons.append("outcome")
    elif outcome is not None and end - outcome > OUTCOME_TAIL_BUFFER:
        # The window extends well past the known resolution point — likely
        # trailing padding (e.g. a short real event padded out to the minimum
        # clip duration upstream) rather than genuine follow-through. Trim
        # back so a teaser/preview sampled near the tail of this window lands
        # on real content, not empty padding.
        trimmed_end = max(outcome + OUTCOME_TAIL_BUFFER, start + MIN_WINDOW)
        if trimmed_end < end:
            end = trimmed_end
            reasons.append("outcome_trim")

    cap = _num(event.get("_cap_dur"), 0.0) if event.get("_is_climax") else MAX_NORMAL_WINDOW
    if cap > 0 and end - start > cap:
        if setup is not None or peak is not None or outcome is not None:
            req_start = setup if setup is not None else start
            req_peak = peak if peak is not None else req_start
            req_end = outcome if outcome is not None else max(req_peak, end)
            if req_end - req_start > cap:
                return None
            start = max(0.0, req_peak - cap * 0.45)
            end = min(source_duration, start + cap)
            if req_start < start:
                start = max(0.0, req_start)
                end = min(source_duration, start + cap)
            if req_end > end:
                end = min(source_duration, req_end)
                start = max(0.0, end - cap)
            reasons.append("cap_preserved_action")
        else:
            start = max(0.0, end - cap)
            reasons.append("cap_no_phase")

    start = round(start, 2)
    end = round(end, 2)
    if end - start < MIN_WINDOW:
        return None
    reason = "+".join(reasons) if reasons else "valid"
    return {**event, "start": start, "end": end, "raw_start": round(raw_start, 2), "raw_end": round(raw_end, 2), "original_start": round(original_start, 2), "original_end": round(original_end, 2), "final_cut_start": start, "final_cut_end": end, "cut_adjustment_reason": reason, "peak_time": peak, "outcome_end": outcome, "window_validation_status": "adjusted" if reasons else "valid", "window_validation_reason": reason}


def install():
    import pipeline.stages.editor as editor
    flag = "_sportreel_window_policy_installed"
    if getattr(editor, flag, False):
        return
    original = editor.cut_clip

    def wrapped(video_path, event, index, slowmo=False, sport="", source_info=None, session_peak=10, target_fps=None):
        try:
            resolved = resolve_window(event, editor._get_duration(video_path))
            if resolved is None:
                return None
            event = resolved
        except Exception:
            pass
        return original(video_path, event, index, slowmo, sport, source_info, session_peak, target_fps)

    editor.cut_clip = wrapped
    setattr(editor, flag, True)

"""Prevent generic highlight pacing from truncating complete performance actions."""
from __future__ import annotations

from typing import Any

_INSTALLED_FLAG = "_sportreel_complete_action_window_policy_installed"
# A complete action that ends this close to the end of the recording is extended to it. The bound is final QA's
# own DEAD_TIME definition ("more than ~2 seconds with no meaningful action", analyzer._QA_REEL_PROMPT), so the
# extension can never add what QA calls dead time. Run 42857524999: drone files stop recording right after the
# ride; the cut ended 0.2-1.6 s before the file end on 15 of 22 catalogued sources, and final QA reported the
# missing fall/exit as PREMATURE_CUT ("just before the fall", "rides the whitewater for another second").
RECORDING_END_TAIL_MAX_SEC = 2.0


def _is_complete_performance_action(event: dict[str, Any]) -> bool:
    contract = str(event.get("performance_reel_contract") or "")
    return contract in {
        "all_usable_waves_per_athlete_v1",
        "all_usable_actions_per_athlete_v1",
    } or bool(event.get("complete_action_window_preserved"))


def _source_path(event: dict[str, Any], video_path: str | None) -> str | None:
    return video_path or event.get("_src") or event.get("source_video") or event.get("source") or None


def _recording_duration(path: str | None) -> float | None:
    if not path:
        return None
    try:
        from pipeline.stages import editor

        duration = float(editor._get_duration(str(path)))
    except Exception:
        return None
    return duration if 0 < duration < float("inf") else None


def extend_to_recording_end(event: dict[str, Any], duration: float | None) -> dict[str, Any]:
    """Let an action that ends within RECORDING_END_TAIL_MAX_SEC of the recording's end run to that end."""
    if duration is None or event.get("_teaser"):
        return event
    refinement = event.get("window_refinement")
    if isinstance(refinement, dict) and "track_lost_before_end" in (refinement.get("reasons") or []):
        return event  # the athlete's track ended there: the tail may show nobody (or someone else)
    try:
        end = float(event.get("end"))
    except (TypeError, ValueError):
        return event
    target_end = duration
    if isinstance(refinement, dict) and not refinement.get("track_lost_in_fall_kept"):
        last_track = refinement.get("last_track_sec")
        if isinstance(last_track, (int, float)) and (duration - float(last_track)) > 1.0:
            # PQ-06 / PQ-11: Never extend past last_track_sec + 1.0s (output_qualification PAD_END_SEC) into empty water.
            target_end = min(duration, float(last_track) + 1.0)
    remaining = target_end - end
    if not (0.0 < remaining <= RECORDING_END_TAIL_MAX_SEC):
        return event
    return {**event, "end": round(target_end, 3), "end_before_recording_tail": round(end, 3),
            "recording_end_tail_sec": round(remaining, 3)}


# Owner rule (cycle 5): the paddle-in that leads directly to the wave belongs to the ride, and the GT starts at the first
# recorded frame when the recording opens on the action (16 of 24 GT rides). The analyzer samples at about one frame per
# second and reports its start in whole/half seconds, so a start within SOURCE_START_SNAP_SEC of the recording start with
# the athlete's track present from the first frames and unbroken up to that start is "the action was already running":
# the cut opens on the first recorded frame. Nothing else moves; a track that appears later, has a hole, or starts after
# the snap window is left exactly as it was (waiting before the paddle-in is not part of the ride).
SOURCE_START_SNAP_SEC = 1.0
TRACK_AT_START_SEC = 0.5


def extend_to_recording_start(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("_teaser") or event.get("start_snapped_to_recording_start") is not None:
        return event                                   # applied once; teasers are not complete actions
    refinement = event.get("window_refinement")
    if not isinstance(refinement, dict) or "athlete_not_in_frame_at_start" in (refinement.get("reasons") or []):
        return event
    try:
        start = float(event.get("start"))
        continuous_from = float(refinement.get("track_continuous_from_sec"))
    except (TypeError, ValueError):
        return event                                   # no evidence about the athlete before the start: do not move
    if start > 0.05 and refinement.get("in_progress_from_recording_start") is True:
        # EXP-14-001: every second from the first recorded frame to `start` shows the actor moving relative to the
        # other people in frame (camera-motion compensated): the action was running when the camera started, at any
        # start, not only within SOURCE_START_SNAP_SEC (0162: analyzer start 1.5 s, GT ride from the first frame).
        return {**event, "start": 0.0, "start_snapped_to_recording_start": round(start, 3),
                "start_snap_evidence": "in_progress_relative_motion"}
    if not (0.05 < start <= SOURCE_START_SNAP_SEC) or continuous_from > TRACK_AT_START_SEC:
        return event
    return {**event, "start": 0.0, "start_snapped_to_recording_start": round(start, 3)}


def ends_with_recording(event: dict[str, Any], video_path: str | None = None) -> bool | None:
    """True when this event's clip will end on the last recorded frame (so its action may be cut by the camera),
    False when the action ends inside the recording, None when the recording's length is unknown.

    Uses the same rules as the cut itself, so ordering decisions made before cutting agree with what is rendered.
    """
    if event.get("_teaser"):
        return None
    duration = _recording_duration(_source_path(event, video_path))
    if duration is None:
        return None
    cut = extend_to_recording_end(extend_through_fall(extend_to_outcome(event, duration), duration), duration)
    try:
        return float(cut.get("end")) >= duration - 0.15
    except (TypeError, ValueError):
        return None


# Seconds a fall takes to resolve on screen: hitting the water, the board, the athlete surfacing. The analyzer
# marks the second the athlete starts to fall as the end; final QA asks for the fall itself ("cut while still
# surfing ... ending in a fall", run 43013005072). Below QA's 2-second DEAD_TIME rule, so the tail cannot add dead
# time. Not tuned on the catalog.
FALL_OUTCOME_TAIL_SEC = 1.5


def extend_through_fall(event: dict[str, Any], duration: float | None) -> dict[str, Any]:
    """Keep the fall in the cut when the analyzer says the action ends in one, clamped to the recording."""
    if event.get("_teaser"):
        return event
    from pipeline.window_refinement import ends_in_fall

    if not ends_in_fall(event):
        return event
    refinement = event.get("window_refinement")
    if isinstance(refinement, dict) and "track_lost_before_end" in (refinement.get("reasons") or []):
        return event  # the window was cut where the athlete's track was lost long before the fall
    try:
        end = float(event.get("end"))
    except (TypeError, ValueError):
        return event
    new_end = end + FALL_OUTCOME_TAIL_SEC
    if duration is not None:
        new_end = min(new_end, duration)
    if not new_end > end:
        return event
    return {**event, "end": round(new_end, 3), "end_before_fall_tail": round(end, 3)}


def extend_to_outcome(event: dict[str, Any], duration: float | None) -> dict[str, Any]:
    """Run an action to the second the analyzer says its outcome resolves, when that is after `end`.

    The analyzer reports `end` (last readable second of the action) and, separately, `outcome_end` ("where the
    outcome fully resolves: landing complete, wave ridden out or athlete falls"), which the prompt calls a firm
    claim. `window_policy.resolve_window` used to apply it, but that cut-clip wrapper is no longer on the
    production path (`quality_preserving_framing.install()` replaces `editor.cut_clip`), so a reported outcome
    after `end` was silently dropped and the fall/exit was cut. Window refinement already clamps `outcome_end`
    to the tracked span, so this never reaches past where the athlete's track was lost.
    """
    if event.get("_teaser"):
        return event
    try:
        end = float(event.get("end"))
        outcome = float(event.get("outcome_end"))
    except (TypeError, ValueError):
        return event
    if duration is not None:
        outcome = min(outcome, duration)
    if not outcome > end:
        return event
    return {**event, "end": round(outcome, 3), "end_before_outcome": round(end, 3)}


# Longest lead-in a cut opens with before the analyzer's `start` (the athlete standing up). Final QA's DEAD_TIME
# rule ("more than ~2 seconds with no meaningful action") bounds it, like the tails above.
SETUP_LEAD_IN_MAX_SEC = 2.0
# Open at most this far before the first frame the athlete's track is seen: the follow crop needs them in frame.
SETUP_TRACK_MARGIN_SEC = 0.3


def extend_to_setup(event: dict[str, Any]) -> dict[str, Any]:
    """Open the cut on the catch and pop-up the analyzer reported as `setup_start`.

    `window_policy.resolve_window` used to apply setup_start, but it left the production path with the cut-clip
    wrapper (see extend_to_outcome), so every ride has opened on an athlete already standing. Against the manual
    catalog (run 43203677423, 22 sources) cuts started a median 1.6 s after the catalogued ride start and lost
    40.7 s of usable ride starts; setup_start capped at SETUP_LEAD_IN_MAX_SEC recovers 19 s of it with no second
    outside the catalogued ride. The cut never opens before the athlete's track is seen (window refinement
    measures it), and without that evidence it does not move.
    """
    if event.get("_teaser") or event.get("start_before_setup_lead_in") is not None:
        return event  # normalization runs before the cut and again for the timeline: apply the lead-in once
    try:
        start = float(event.get("start"))
        setup = float(event.get("setup_start"))
    except (TypeError, ValueError):
        return event
    refinement = event.get("window_refinement")
    if not isinstance(refinement, dict) or "athlete_not_in_frame_at_start" in (refinement.get("reasons") or []):
        return event
    try:
        first_seen = float(refinement.get("setup_first_track_sec"))
    except (TypeError, ValueError):
        return event
    new_start = max(setup, start - SETUP_LEAD_IN_MAX_SEC, first_seen - SETUP_TRACK_MARGIN_SEC, 0.0)
    # FIX-PQ-11-001: where the stitched actor is seen MOVING back to an earlier second (motion-supported onset,
    # pipeline.action_onset; bound and motion threshold from the sport profile), the build-up starts there - beyond
    # the fixed lead-in cap (0115 paddle-in), but never into stationary waiting (0140), which stops the walk-back.
    try:
        onset = float(refinement.get("onset_motion_from_sec"))
    except (TypeError, ValueError):
        onset = None
    if onset is not None and onset < new_start:
        new_start = max(setup, onset, 0.0)
    if not new_start < start - 0.05:
        return event
    return {**event, "start": round(new_start, 3), "start_before_setup_lead_in": round(start, 3)}


def normalize_complete_action_event(event: dict[str, Any], video_path: str | None = None) -> dict[str, Any]:
    """Persist the exact full action window used by the renderer and final QA.

    This normalization is intentionally applied both before cutting and when
    `_events_out` is built. A temporary cut wrapper alone is insufficient because
    identity/continuity gates later derive evidence from the persisted event.
    """
    effective = dict(event)
    if effective.get("_teaser"):
        return effective
    # Every sport, not only the surf contract below: the outcome is the analyzer's own claim, and the tail bound
    # comes from QA's generic DEAD_TIME rule.
    duration = _recording_duration(_source_path(effective, video_path))
    effective = extend_to_setup(effective)
    effective = extend_to_recording_start(effective)
    effective = extend_to_outcome(effective, duration)
    effective = extend_through_fall(effective, duration)
    effective = extend_to_recording_end(effective, duration)
    if not _is_complete_performance_action(effective):
        return effective
    effective.pop("_cap_dur", None)
    effective.pop("_single_clip_cap", None)
    effective["_is_climax"] = True
    try:
        start = float(effective.get("start"))
        end = float(effective.get("end"))
    except (TypeError, ValueError):
        return effective
    if end < start:
        start, end = end, start
    effective["final_cut_start"] = round(start, 3)
    effective["final_cut_end"] = round(end, 3)
    effective["complete_action_window_preserved"] = True
    return effective


def install() -> None:
    """Remove historical pacing caps and persist the same complete action window."""
    from pipeline.stages import editor

    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original_cut_clip = editor.cut_clip
    original_rendered_timeline = getattr(editor, "_events_with_rendered_timeline", None)

    def cut_complete_action(
        video_path: str,
        event: dict[str, Any],
        index: int,
        slowmo: bool = False,
        sport: str = "",
        source_info: dict[str, Any] | None = None,
        session_peak: int = 10,
        target_fps: int | None = None,
    ):
        effective = normalize_complete_action_event(event, video_path)
        return original_cut_clip(
            video_path,
            effective,
            index,
            slowmo,
            sport,
            source_info,
            session_peak,
            target_fps,
        )

    editor.cut_clip = cut_complete_action
    if callable(original_rendered_timeline):
        def rendered_timeline_with_complete_actions(events, clip_paths, transitions=None):
            normalized = [
                normalize_complete_action_event(event)
                for event in list(events or [])
            ]
            return original_rendered_timeline(normalized, clip_paths, transitions)

        editor._events_with_rendered_timeline = rendered_timeline_with_complete_actions
    setattr(editor, _INSTALLED_FLAG, True)

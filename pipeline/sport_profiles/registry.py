"""Profile lookup. Unknown activities get GENERIC (no domain rules, Core behaviour only)."""
from __future__ import annotations

from typing import Any

from pipeline.sport_profiles.base import OnsetPolicy, SportProfile
from pipeline.sport_profiles.football import FOOTBALL
from pipeline.sport_profiles.surfing import SURFING

GENERIC = SportProfile(profile_id="generic")
_PROFILES: dict[str, SportProfile] = {}

SKATEBOARDING = SportProfile(
    profile_id="skateboarding",
    aliases=frozenset({"skate", "skater", "longboarding"}),
    event_terms=frozenset({"ollie", "kickflip", "heelflip", "grind", "boardslide", "manual_pad", "drop_in", "skate_trick", "skate_line"}),
    failed_attempt_terms=frozenset({"bails immediately", "steps off immediately", "aborted run", "never lands"}),
    failed_attempt_reasons=frozenset({"immediate_bail", "aborted_attempt"}),
    coverage_first=True,
    action_types=frozenset({"skate_line", "skate_trick", "grind", "ollie"}),
    action_phases=("push_in", "setup", "execution", "landing"),
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.25, max_lead_sec=4.0, step_sec=1.0),
    rescue_event_type="skate_line",
)

SNOWBOARDING = SportProfile(
    profile_id="snowboarding",
    aliases=frozenset({"snowboard", "skiing", "ski", "freeski"}),
    event_terms=frozenset({"snowboard_carve", "ski_carve", "powder_run", "slalom", "halfpipe", "jib_rail", "ski_run", "snow_run"}),
    failed_attempt_terms=frozenset({"falls immediately", "stops before jump", "aborted run"}),
    failed_attempt_reasons=frozenset({"immediate_fall", "aborted_attempt"}),
    coverage_first=True,
    action_types=frozenset({"snow_run", "powder_run", "slalom", "jib_rail"}),
    action_phases=("approach", "takeoff", "air_or_turn", "landing"),
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.3, max_lead_sec=5.0, step_sec=1.0),
    rescue_event_type="snow_run",
)

CYCLING = SportProfile(
    profile_id="cycling",
    aliases=frozenset({"mtb", "mountain_biking", "bmx", "road_cycling", "bike"}),
    event_terms=frozenset({"peloton_sprint", "berm_corner", "trail_descent", "bunny_hop", "tailwhip", "bike_climb", "bike_run"}),
    failed_attempt_terms=frozenset({"unclips immediately", "stops before feature", "aborted attempt"}),
    failed_attempt_reasons=frozenset({"aborted_attempt", "immediate_stop"}),
    coverage_first=True,
    action_types=frozenset({"peloton_sprint", "berm_corner", "trail_descent", "bike_run"}),
    action_phases=("approach", "entry", "feature", "exit"),
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.35, max_lead_sec=4.0, step_sec=1.0),
    rescue_event_type="bike_run",
)

BASKETBALL = SportProfile(
    profile_id="basketball",
    aliases=frozenset({"streetball", "hoops", "3x3"}),
    event_terms=frozenset({"layup", "slam_dunk", "dunk", "three_pointer", "jump_shot", "rebound", "crossover_dribble", "alley_oop"}),
    failed_attempt_terms=frozenset({"not involved", "dead ball standing"}),
    failed_attempt_reasons=frozenset({"not_involved"}),
    coverage_first=True,
    action_types=frozenset({"layup", "dunk", "jump_shot", "rebound", "crossover_dribble"}),
    action_phases=("setup", "drive_or_gather", "release_or_contest", "outcome"),
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.25, max_lead_sec=3.5, step_sec=1.0),
    rescue_event_type="court_play",
)

TENNIS = SportProfile(
    profile_id="tennis",
    aliases=frozenset({"padel", "pickleball", "racquet"}),
    event_terms=frozenset({"tennis_serve", "forehand", "backhand", "net_volley", "overhead_smash", "baseline_rally", "drop_shot"}),
    failed_attempt_terms=frozenset({"ball toss aborted", "walking between points"}),
    failed_attempt_reasons=frozenset({"between_points", "aborted_serve"}),
    coverage_first=True,
    action_types=frozenset({"tennis_serve", "baseline_rally", "forehand", "backhand", "net_volley"}),
    action_phases=("split_step", "preparation", "stroke", "recovery"),
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.2, max_lead_sec=3.0, step_sec=1.0),
    rescue_event_type="rally_point",
)

ATHLETICS = SportProfile(
    profile_id="athletics",
    aliases=frozenset({"running", "track", "sprint", "hurdles", "crossfit"}),
    event_terms=frozenset({"track_sprint", "hurdle_clearance", "long_jump", "high_jump", "javelin_throw", "shot_put", "interval_rep"}),
    failed_attempt_terms=frozenset({"false start", "standing at line only"}),
    failed_attempt_reasons=frozenset({"false_start", "not_started"}),
    coverage_first=True,
    action_types=frozenset({"track_sprint", "hurdle_clearance", "long_jump", "interval_rep"}),
    action_phases=("set", "acceleration", "max_effort", "finish"),
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.3, max_lead_sec=3.0, step_sec=1.0),
    rescue_event_type="athletic_rep",
)


def register(profile: SportProfile) -> SportProfile:
    _PROFILES[profile.profile_id] = profile
    return profile


for _p in (SURFING, FOOTBALL, SKATEBOARDING, SNOWBOARDING, CYCLING, BASKETBALL, TENNIS, ATHLETICS):
    register(_p)


def all_profiles() -> list[SportProfile]:
    return list(_PROFILES.values())


def profile_for(activity: str | None) -> SportProfile:
    for p in _PROFILES.values():
        if p.matches_activity(activity or ""):
            return p
    return GENERIC


def profile_for_event(event: dict[str, Any], activity: str = "") -> SportProfile:
    """Activity first (explicit), then the event's own sport, then the first profile whose terms cover the event."""
    for hint in (activity, event.get("sport"), event.get("sport_profile_id")):
        p = profile_for(hint)
        if p is not GENERIC:
            return p
    for p in _PROFILES.values():
        if p.covers_event(event, activity):
            return p
    return GENERIC


def default_profile() -> SportProfile:
    """The deployment's profile when an event does not say its sport (SPORTREEL_DEFAULT_PROFILE, default surfing:
    the only profile with labelled data today). Explicit configuration instead of a surf assumption in Core code."""
    import os
    p = profile_for(os.getenv("SPORTREEL_DEFAULT_PROFILE", "surfing"))
    return p

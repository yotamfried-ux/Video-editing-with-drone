"""Profile lookup. Unknown activities get GENERIC (no domain rules, Core behaviour only)."""
from __future__ import annotations

from typing import Any

from pipeline.sport_profiles.base import SportProfile
from pipeline.sport_profiles.football import FOOTBALL
from pipeline.sport_profiles.surfing import SURFING

GENERIC = SportProfile(profile_id="generic")
_PROFILES: dict[str, SportProfile] = {}


def register(profile: SportProfile) -> SportProfile:
    _PROFILES[profile.profile_id] = profile
    return profile


for _p in (SURFING, FOOTBALL):
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

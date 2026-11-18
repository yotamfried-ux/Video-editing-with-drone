"""Sport / performance profiles: the domain layer of the performance-reel engine (cycle 11).

The Core engine (perception, tracking, identity continuity, windows, selection, dedup, framing, render, QA, review,
evidence, storage) takes evidence and applies generic logic. Everything that depends on WHAT the performance is
(which words name an action, what a failed attempt is, how an action begins, which appearance attributes may tell
two people apart) lives in a profile. A new sport adds a profile (+ examples, GT, calibration), not a pipeline.

    from pipeline.sport_profiles import profile_for, profile_for_event
"""
from pipeline.sport_profiles.base import OnsetPolicy, SportProfile
from pipeline.sport_profiles.registry import (GENERIC, all_profiles, default_profile, profile_for,
                                              profile_for_event, register)

__all__ = ["SportProfile", "OnsetPolicy", "GENERIC", "profile_for", "profile_for_event", "default_profile", "register",
           "all_profiles"]

"""Surfing profile: the definitions that used to be hard-coded in Core modules (moved verbatim, behaviour unchanged)."""
from pipeline.sport_profiles.base import OnsetPolicy, SportProfile

SURFING = SportProfile(
    profile_id="surfing",
    aliases=frozenset({"surf", "surfer", "longboard", "shortboard", "bodyboard"}),
    # was performance_reel_policy._SURF_TERMS
    event_terms=frozenset({"surf", "surfing", "surfer", "wave", "longboard", "shortboard", "cutback", "bottom_turn",
                           "carve", "snap", "barrel", "tube_ride", "wave_catch", "surf_ride"}),
    # was performance_reel_policy._FAILED_TAKEOFF_TERMS and the hard_reject_reason set
    failed_attempt_terms=frozenset({"failed takeoff", "falls immediately", "fell immediately", "immediate fall",
                                    "wipeout at takeoff", "misses the wave", "never stands", "does not stand"}),
    failed_attempt_reasons=frozenset({"failed_takeoff", "no_ride_established", "immediate_fall"}),
    coverage_first=True,
    action_types=frozenset({"wave_ride", "maneuver", "wipeout"}),
    action_phases=("paddle_in", "catch", "pop_up", "ride", "outcome"),
    # Paddle-in is the surfer moving; sitting/lying still on the board is waiting (0140 vs 0115, cycle 11).
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.2, max_lead_sec=6.0, step_sec=1.0),
    # was stages.identity._TEXT_ATTRIBUTE_REASONS (FIX-PQ-10-003)
    reviewable_attribute_conflicts=frozenset({"wetsuit_vs_bare_or_swimsuit_conflict", "conflicting_equipment_color",
                                              "incompatible_swimwear_or_category"}),
    framing_subject_height_ratio=0.16,   # was quality_preserving_framing: 0.16 if sport == "surfing" else 0.18
)

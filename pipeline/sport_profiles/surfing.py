"""Surfing profile: the definitions that used to be hard-coded in Core modules (moved verbatim, behaviour unchanged)."""
from pipeline.sport_profiles.base import ActionValidityPolicy, OnsetPolicy, SportProfile

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
    # in_progress_min_relative_motion: a surfer paddling or riding moves >= 1 body height/s relative to the other
    # people in the water; one waiting does not (camera pans cancel out). EXP-14-001.
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.2, max_lead_sec=6.0, step_sec=1.0,
                      in_progress_min_relative_motion=1.0),
    # Owner policy (cycle 14): prone, kneeling and standing riding are all valid surfing, active whitewater riding
    # included; a take-off that never gets past the pop-up and ends in the water is not a ride. FIX-PQ-14-002.
    action_validity=ActionValidityPolicy(
        established_states=frozenset({"prone_riding", "kneeling_riding", "standing_riding"}),
        transitional_states=frozenset({"popping_up"}),
        other_states=frozenset({"paddling", "in_water", "not_visible"}),
        min_established_sec=2.0,
        state_definitions=(
            ("paddling", "lying on the board and paddling with the arms; the wave is not yet carrying the board"),
            ("popping_up", "hands AND feet (or knees) on the board pushing up, hips raised: a stand-up in progress"),
            ("prone_riding", "lying on the board while the wave carries it (bodyboard or prone surfing), in control"),
            ("kneeling_riding", "on the knees on the board with the torso upright while the wave carries it"),
            ("standing_riding", "on the feet on the board while the wave or whitewater carries it"),
            ("in_water", "off the board, in the water (fallen, wiped out or swimming)"),
            ("not_visible", "the target cannot be seen in this frame"),
        ),
    ),
    # was stages.identity._TEXT_ATTRIBUTE_REASONS (FIX-PQ-10-003)
    reviewable_attribute_conflicts=frozenset({"wetsuit_vs_bare_or_swimsuit_conflict", "conflicting_equipment_color",
                                              "incompatible_swimwear_or_category"}),
    framing_subject_height_ratio=0.16,   # was quality_preserving_framing: 0.16 if sport == "surfing" else 0.18
)

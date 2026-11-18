"""Football profile (cycle 11 architecture proof). Definitions only: NO accuracy on real football is claimed; it has
no labelled football footage, model calibration or GT yet (docs/architecture/MULTI-SPORT-PERFORMANCE-ENGINE.md)."""
from pipeline.sport_profiles.base import OnsetPolicy, SportProfile

FOOTBALL = SportProfile(
    profile_id="football",
    aliases=frozenset({"soccer", "futsal"}),
    event_terms=frozenset({"pass", "shot", "goal", "dribble", "tackle", "interception",
                           "ball_receive", "first_touch", "save", "header", "cross", "defensive_action"}),
    failed_attempt_terms=frozenset({"loses the ball immediately", "never touches the ball", "not involved"}),
    failed_attempt_reasons=frozenset({"not_involved", "ball_never_reached"}),
    coverage_first=True,
    action_types=frozenset({"ball_receive", "dribble", "pass", "shot", "goal", "tackle", "interception",
                            "defensive_action"}),
    action_phases=("build_up", "ball_contact", "action", "outcome"),
    # A build-up is the player moving into the play; standing still while the ball is elsewhere is not the action.
    onset=OnsetPolicy(requires_motion=True, min_motion_body_heights_per_sec=0.3, max_lead_sec=4.0, step_sec=1.0),
    # Team kits are shared: a colour/sleeve conflict is not owner-reviewable evidence of one person. (Making the
    # identity engine treat kit colour as non-evidence for SAME identity is future work: docs/architecture.)
    reviewable_attribute_conflicts=frozenset(),
)

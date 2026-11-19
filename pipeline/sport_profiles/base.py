"""Profile contract. Only fields with a real consumer in the engine are defined here (no speculative interface)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OnsetPolicy:
    """How the action's build-up is recognised before the analyzer's 'main moment'.

    Consumer: pipeline.action_onset.motion_supported_onset (Core) and
    pipeline.complete_action_window_policy.extend_to_setup (Core).
    `requires_motion`: the build-up (surf paddle-in, a run onto the ball) is the actor moving; standing still is
    waiting, not part of the action. `min_motion_body_heights_per_sec`: the actor's displacement per second,
    measured in their own box heights (scale-free for drone height and zoom).
    `max_lead_sec`: upper bound of how far before the main moment a build-up may start.
    `in_progress_min_relative_motion`: when set, a recording that OPENS on the actor already moving at least this
    fast relative to the other people in frame (camera-motion compensated, actor box heights per second) opens on
    the action, so the cut starts on the first recorded frame (pipeline.action_onset.in_progress_from_recording_start).
    None disables it. Consumer: window_refinement (measurement) and complete_action_window_policy (the cut).
    """
    requires_motion: bool = False
    min_motion_body_heights_per_sec: float = 0.0
    max_lead_sec: float = 2.0
    step_sec: float = 1.0
    in_progress_min_relative_motion: float | None = None


@dataclass(frozen=True)
class ActionValidityPolicy:
    """What counts as an ESTABLISHED action, observed frame by frame (consumer: pipeline.action_validity, Core).

    `established_states`: per-frame states that are the action itself, once established (surfing: prone, kneeling
    AND standing riding - standing is not required). `transitional_states`: attempt states that are not yet the
    action (surfing: a pop-up in progress, hands and feet on the board). `min_established_sec`: the shortest
    continuous established run that is a usable action. Empty `established_states` disables the check.
    """
    established_states: frozenset[str] = frozenset()
    transitional_states: frozenset[str] = frozenset()
    other_states: frozenset[str] = frozenset({"in_water", "not_visible"})
    min_established_sec: float = 2.0
    state_definitions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SportProfile:
    profile_id: str
    aliases: frozenset[str] = frozenset()
    # Words that place an analyzer event under this profile's coverage contract (consumer: performance_reel_policy).
    event_terms: frozenset[str] = frozenset()
    # Analyzer statements that an attempt never became a usable action (consumer: performance_reel_policy).
    failed_attempt_terms: frozenset[str] = frozenset()
    failed_attempt_reasons: frozenset[str] = frozenset()
    # Coverage-first: every usable action of the athlete belongs in their reel (a below-threshold score alone does
    # not drop it; it is UNCERTAIN and reviewed). Consumer: performance_reel_policy.classify_event_eligibility.
    coverage_first: bool = False
    # Action vocabulary for labelled examples / GT and PerformanceEvent.action_type (consumer: performance_event).
    action_types: frozenset[str] = frozenset()
    action_phases: tuple[str, ...] = ()
    onset: OnsetPolicy = field(default_factory=OnsetPolicy)
    action_validity: ActionValidityPolicy = field(default_factory=ActionValidityPolicy)
    # Identity: description-attribute conflicts that are only TEXT under varying light, so a split on them alone is
    # reviewable by the owner (consumer: stages.identity._text_attribute_split_reviewed). Empty = never reviewable.
    reviewable_attribute_conflicts: frozenset[str] = frozenset()
    # Other people in the frame are never a rejection reason by themselves (Core multi-actor policy).
    other_actors_allowed: bool = True
    # Framing style: the athlete's target height as a share of the 9:16 frame (consumer: quality_preserving_framing).
    framing_subject_height_ratio: float = 0.18

    def matches_activity(self, activity: str) -> bool:
        a = str(activity or "").strip().lower()
        return bool(a) and (a == self.profile_id or a in self.aliases)

    def text_of(self, event: dict[str, Any], activity: str = "") -> str:
        parts = [activity, event.get("type"), event.get("event_type"), event.get("description"),
                 event.get("sport"), event.get("action_type")]
        return " ".join(str(p) for p in parts if p).lower()

    def covers_event(self, event: dict[str, Any], activity: str = "") -> bool:
        text = self.text_of(event, activity)
        return any(term in text for term in self.event_terms)

    def is_failed_attempt(self, event: dict[str, Any], activity: str = "") -> bool:
        reason = str(event.get("hard_reject_reason") or "").strip().lower()
        if reason in self.failed_attempt_reasons:
            return True
        return any(term in self.text_of(event, activity) for term in self.failed_attempt_terms)

"""PerformanceEvent: the sport-agnostic event contract (cycle 11).

It is a typed VIEW over the event dict the pipeline already passes around (analyzer -> perception -> windows ->
identity -> render -> QA -> manifest); it does not replace it. Storage, render, review and distribution keep their
contracts. Fields a profile or a stage does not provide stay None and are listed in `missing_fields`: never filled
with invented values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FIELDS = ("sport_profile_id", "event_id", "source_sha256", "source_start_frame", "source_end_frame",
          "primary_actor_id", "other_actor_ids", "action_type", "action_phases", "action_start_evidence",
          "action_end_evidence", "actor_tracking_evidence", "action_validity", "confidence", "uncertainty_reasons",
          "editorial_priority", "selection_status", "qa_status", "evidence_references")


@dataclass
class PerformanceEvent:
    sport_profile_id: str
    event_id: str | None = None
    source_sha256: str | None = None
    source_start_frame: int | None = None
    source_end_frame: int | None = None
    primary_actor_id: str | None = None
    other_actor_ids: list[str] = field(default_factory=list)
    action_type: str | None = None
    action_phases: dict[str, float] = field(default_factory=dict)     # phase name -> source second
    action_start_evidence: dict[str, Any] | None = None
    action_end_evidence: dict[str, Any] | None = None
    actor_tracking_evidence: dict[str, Any] | None = None
    action_validity: dict[str, Any] | None = None
    confidence: float | None = None
    uncertainty_reasons: list[str] = field(default_factory=list)
    editorial_priority: float | None = None
    selection_status: str | None = None
    qa_status: str | None = None
    evidence_references: list[str] = field(default_factory=list)

    @property
    def missing_fields(self) -> list[str]:
        empty = (None, [], {})
        return [f for f in FIELDS if getattr(self, f) in empty]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "missing_fields": self.missing_fields}


def _sha(event: dict[str, Any]) -> str | None:
    ref = str(event.get("event_source_ref") or event.get("source_sha256") or "")
    return ref.split(":", 1)[1] if ref.startswith("sha256:") else (ref or None)


def from_pipeline_event(event: dict[str, Any], *, fps: float | None = None, profile_id: str | None = None) -> PerformanceEvent:
    """Typed view of an existing pipeline event. Frames only when fps is known."""
    from pipeline.sport_profiles import profile_for_event
    pid = profile_id or profile_for_event(event).profile_id
    start, end = event.get("start"), event.get("end")
    phases = {k: float(event[v]) for k, v in (("setup", "setup_start"), ("main", "start"), ("peak", "peak_time"),
                                               ("outcome", "outcome_end")) if event.get(v) is not None}
    refinement = event.get("window_refinement") if isinstance(event.get("window_refinement"), dict) else {}
    track = event.get("target_track_id")
    return PerformanceEvent(
        sport_profile_id=pid,
        event_id=event.get("event_uid"),
        source_sha256=_sha(event),
        source_start_frame=int(round(float(start) * fps)) if fps and start is not None else None,
        source_end_frame=int(round(float(end) * fps)) if fps and end is not None else None,
        primary_actor_id=None if track in (None, "") else str(track),
        action_type=event.get("action_type") or event.get("type"),
        action_phases=phases,
        action_start_evidence=({"onset_motion_from_sec": refinement.get("onset_motion_from_sec"),
                                "steps": refinement.get("onset_motion_steps")}
                               if refinement.get("onset_motion_from_sec") is not None else None),
        action_end_evidence=({"last_track_sec": refinement.get("last_track_sec")} if refinement.get("last_track_sec") is not None else None),
        actor_tracking_evidence=({"status": event.get("perception_evidence_status"), "track": track}
                                 if event.get("perception_evidence_status") else None),
        action_validity=event.get("eligibility") if isinstance(event.get("eligibility"), dict) else None,
        confidence=(float(event["score"]) / 10.0) if isinstance(event.get("score"), (int, float)) else None,
        selection_status=("selected" if event.get("selected") else None),
    )


def to_pipeline_event(pe: PerformanceEvent, *, fps: float) -> dict[str, Any]:
    """A labelled PerformanceEvent (examples / GT / an external detector) as the event dict the engine consumes."""
    if pe.source_start_frame is None or pe.source_end_frame is None:
        raise ValueError("a PerformanceEvent needs source frames to become a pipeline event")
    ev: dict[str, Any] = {"start": round(pe.source_start_frame / fps, 3), "end": round(pe.source_end_frame / fps, 3),
                          "type": pe.action_type or "highlight", "action_type": pe.action_type,
                          "sport": pe.sport_profile_id, "score": int(round((pe.confidence or 0.0) * 10))}
    if "setup" in pe.action_phases:
        ev["setup_start"] = pe.action_phases["setup"]
    if "outcome" in pe.action_phases:
        ev["outcome_end"] = pe.action_phases["outcome"]
    if pe.primary_actor_id is not None:
        ev["target_track_id"] = pe.primary_actor_id
    if pe.event_id:
        ev["event_uid"] = pe.event_id
    if pe.source_sha256:
        ev["event_source_ref"] = f"sha256:{pe.source_sha256}"
    return ev

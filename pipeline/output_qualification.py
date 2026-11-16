"""Output-level qualification: one typed, digest-bound proof per rendered reel part.

The publishable flag is derived here from the evidence carried by the part's events - never copied from a model
answer or a client. Every failed requirement becomes a `qualification:<code>` technical issue on the part, so it
blocks `render_ready`, reaches `draft_publishability.technical_issues` and is refused by the approval API (which
already fails closed on any technical issue). A blocked part is still uploaded for review: nothing disappears.

Contracts (spec docs/plans/2026-11-15-pipeline-root-causes-and-preventive-architecture.md):

* RC-03 SurfActionEligibility - `VALID_COMPLETE_ACTION | INVALID_ACTION | UNCERTAIN`. Explicit negative evidence
  (a stated failed takeoff / no ride) is INVALID whatever the score. VALID needs positive evidence from more than
  the analyzer's words: a positive rating, the target actor bound by the tracker (sidecar), CV activity of that
  track (`active`, or board association), and a coherent window. A CV contradiction (the target track measured as
  waiting / passer-by) or any missing evidence is UNCERTAIN. Only VALID can publish; UNCERTAIN is kept for review.
* RC-04/05 ActionInterval - requested (analyzer), validated (tracked actor span), rendered and QA re-edit windows
  are kept apart. A rendered window may not run past the last verified actor frame by more than the permitted
  pad (a measured fall or a recording that ended mid-ride are recorded as such, not as an invented tail), and a
  track gap longer than MAX_TRACK_GAP_SEC is an unproven identity continuity.
* RC-01/02 identity - a multi-source reel needs an identity gate `pass` decision backed by image evidence; an
  unconfirmed or ungated multi-source reel never publishes. A single-source, single-person reel claims nothing
  across sources and needs no cross-source proof.
* RC-08 lineage - every shot needs its canonical event id and a content-addressed source reference.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

SCHEMA = "sportreel.output_qualification.v1"

VALID = "VALID_COMPLETE_ACTION"
INVALID = "INVALID_ACTION"
UNCERTAIN = "UNCERTAIN"

MIN_POSITIVE_SCORE = 6
PAD_END_SEC = 1.0          # window_refinement.DEFAULT_PAD_END_SEC
PAD_START_SEC = 0.5        # window_refinement.DEFAULT_PAD_START_SEC
FALL_TAIL_MAX_SEC = 2.5    # window_refinement.FALL_TRACK_LOSS_MAX_SEC
MAX_TRACK_GAP_SEC = 2.0    # longer gaps: the same id may be another person (0094, run 42891165218)
EQUIPMENT_MIN_RATIO = 0.20

ISSUE_PREFIX = "qualification:"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _performance_policy():
    """pipeline.performance_reel_policy, also when this module was loaded by file path (repository root added)."""
    try:
        from pipeline import performance_reel_policy
        return performance_reel_policy
    except ModuleNotFoundError:
        import sys
        from pathlib import Path
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        from pipeline import performance_reel_policy
        return performance_reel_policy


# ---------------------------------------------------------------- RC-03

def classify_action(event: dict[str, Any], activity: str = "") -> dict[str, Any]:
    """Typed action eligibility with the evidence it rests on."""
    policy = _performance_policy()
    is_explicit_failed_takeoff, is_surf_event = policy.is_explicit_failed_takeoff, policy.is_surf_event

    positive: list[str] = []
    missing: list[str] = []
    negative: list[str] = []
    if is_surf_event(event, activity) and is_explicit_failed_takeoff(event, activity):
        negative.append("explicit_no_ride_statement")
    score = _num(event.get("score")) or 0.0
    (positive if score >= MIN_POSITIVE_SCORE else missing).append(
        "analyzer_positive_rating" if score >= MIN_POSITIVE_SCORE else "analyzer_rating_below_threshold")
    if event.get("perception_evidence_status") == "tracker_sidecar" and event.get("target_track_id") not in (None, ""):
        positive.append("target_actor_tracked")
    else:
        missing.append("target_actor_not_tracked")
    state = str(event.get("athlete_activity_state") or "")
    equipment = _num(event.get("equipment_association_ratio")) or 0.0
    if state == "active" or equipment >= EQUIPMENT_MIN_RATIO:
        positive.append("cv_activity_of_target_track" if state == "active" else "board_associated_with_target")
    elif state in {"waiting", "background_passerby"}:
        negative.append(f"cv_target_track_{state}")
    else:
        missing.append("cv_activity_unmeasured")
    start, end = _num(event.get("start")), _num(event.get("end"))
    phases = [_num(event.get(k)) for k in ("setup_start", "peak_time", "outcome_end")]
    if start is None or end is None or end <= start:
        missing.append("window_incoherent")
    elif any(p is not None and not (start - PAD_START_SEC - 3.0 <= p <= end + PAD_END_SEC + 3.0) for p in phases):
        missing.append("phase_times_outside_window")
    else:
        positive.append("coherent_window")

    if "explicit_no_ride_statement" in negative:
        verdict = INVALID
    elif negative or missing:
        verdict = UNCERTAIN
    else:
        verdict = VALID
    return {"verdict": verdict, "positive": positive, "missing": missing, "negative": negative}


# ---------------------------------------------------------------- RC-04 / RC-05

def action_interval(event: dict[str, Any]) -> dict[str, Any]:
    """Requested / validated / rendered / QA windows of one shot and the problems between them."""
    refinement = event.get("window_refinement") if isinstance(event.get("window_refinement"), dict) else {}
    requested = [_num(event.get("llm_start") or event.get("original_start") or event.get("start")),
                 _num(event.get("llm_end") or event.get("original_end") or event.get("end"))]
    first, last = _num(refinement.get("first_track_sec")), _num(refinement.get("last_track_sec"))
    rendered = [_num(event.get("final_cut_start") if event.get("final_cut_start") is not None else event.get("start")),
                _num(event.get("final_cut_end") if event.get("final_cut_end") is not None else event.get("end"))]
    qa = [_num(event.get("_qa_reedit_selector_start")), _num(event.get("_qa_reedit_selector_end"))]
    gap = _num(refinement.get("max_track_gap_sec")) or 0.0
    gap_at = _num(refinement.get("max_track_gap_start_sec"))
    issues: list[str] = []
    notes: list[str] = []
    if first is None or last is None:
        issues.append("actor_span_unvalidated")
    else:
        if rendered[1] is not None and rendered[1] > last + PAD_END_SEC:
            tail = rendered[1] - last
            if refinement.get("track_lost_in_fall_kept") and tail <= FALL_TAIL_MAX_SEC + PAD_END_SEC:
                notes.append("tail_is_measured_fall")
            elif event.get("recording_end_tail_sec") is not None:
                issues.append("tail_after_actor_lost_to_recording_end")
            else:
                issues.append("tail_beyond_verified_actor")
        lead_floor = _num(refinement.get("setup_first_track_sec"))
        # The target track seen continuously (no hole > 0.4 s) from an earlier second validates the lead as well:
        # `first` only looks one second before the analyzer's start (window_refinement.continuous_presence_from).
        continuous = _num(refinement.get("track_continuous_from_sec"))
        floor = min(v for v in (first, lead_floor, continuous) if v is not None)
        if rendered[0] is not None and rendered[0] < floor - PAD_START_SEC:
            issues.append("lead_before_verified_actor")
        if gap > MAX_TRACK_GAP_SEC and gap_at is not None and rendered[0] is not None and rendered[1] is not None \
                and rendered[0] <= gap_at <= rendered[1]:
            issues.append("track_gap_identity_continuity_unproven")
    if event.get("recording_end_tail_sec") is not None:
        notes.append("source_limited_recording_end")
    return {
        "event_uid": event.get("event_uid"),
        "source_ref": event.get("event_source_ref"),
        "actor_track": event.get("target_track_id"),
        "requested_window": requested,
        "validated_actor_span": [first, last],
        "rendered_window": rendered,
        "qa_reedit_window": qa if any(v is not None for v in qa) else None,
        "max_track_gap_sec": gap,
        "issues": issues,
        "notes": notes,
    }


# ---------------------------------------------------------------- RC-01 / RC-02

def identity_verdict(events: list[dict[str, Any]]) -> dict[str, Any]:
    sources = {str(e.get("event_source_ref") or e.get("source_video") or e.get("_src") or "") for e in events}
    # One actor per source: its source-local track when tracked, else the analyzer's person id.
    people = {(str(e.get("event_source_ref") or e.get("source_video") or ""),
               str(e.get("target_track_id") or e.get("person_id") or "")) for e in events}
    gates = [e.get("identity_gate") for e in events]
    decisions = {g.get("decision") for g in gates if isinstance(g, dict)}
    proofs = [g.get("evidence_digest") for g in gates if isinstance(g, dict) and g.get("evidence_digest")]
    if len(sources) <= 1 and len(people) <= 1:
        return {"verdict": "MATCH", "basis": "single_source_single_person", "pairwise_proofs": [],
                "has_unconfirmed_edges": False}
    if len(sources) <= 1:
        return {"verdict": "UNCERTAIN", "basis": "several_people_in_one_source_reel", "pairwise_proofs": [],
                "has_unconfirmed_edges": True}
    if decisions == {"pass"} and all(isinstance(g, dict) for g in gates) and proofs:
        return {"verdict": "MATCH", "basis": "identity_gate_pass_with_image_evidence",
                "pairwise_proofs": sorted(set(proofs)), "has_unconfirmed_edges": False}
    basis = "identity_gate_not_applied" if not decisions else "identity_gate_" + "_".join(sorted(map(str, decisions)))
    return {"verdict": "UNCERTAIN", "basis": basis, "pairwise_proofs": sorted(set(proofs)),
            "has_unconfirmed_edges": True}


# ---------------------------------------------------------------- the part

def build_inputs(events: list[dict[str, Any]], activity: str = "") -> dict[str, Any]:
    """Evidence-derived requirements of one part, before final QA and upload."""
    shots = [e for e in events or [] if isinstance(e, dict) and not e.get("_teaser")]
    entries: list[dict[str, Any]] = []
    issues: list[str] = []
    for event in shots:
        eligibility = classify_action(event, activity)
        interval = action_interval(event)
        ref = str(event.get("event_source_ref") or "")
        entries.append({"event_uid": event.get("event_uid"), "source_sha256": ref[7:] if ref.startswith("sha256:") else None,
                        "source_frame_range_sec": interval["rendered_window"], "actor_track_uid":
                        f"{ref}#{event.get('target_track_id')}" if ref and event.get("target_track_id") else None,
                        "eligibility": eligibility, "interval": interval})
        label = str(event.get("event_uid") or "?")[:24]
        if eligibility["verdict"] != VALID:
            issues.append(f"{ISSUE_PREFIX}action_{eligibility['verdict'].lower()}:{label}")
        issues.extend(f"{ISSUE_PREFIX}{code}:{label}" for code in interval["issues"])
        if not event.get("event_uid") or not ref.startswith("sha256:"):
            issues.append(f"{ISSUE_PREFIX}lineage_incomplete:{label}")
    identity = identity_verdict(shots)
    if identity["verdict"] != "MATCH" or identity["has_unconfirmed_edges"]:
        issues.append(f"{ISSUE_PREFIX}identity_{identity['basis']}")
    if not shots:
        issues.append(f"{ISSUE_PREFIX}no_shots")
    return {"identity": identity, "events": entries, "issues": list(dict.fromkeys(issues)),
            "source_shas": sorted({e["source_sha256"] for e in entries if e["source_sha256"]})}


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def finalize(row: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    """The qualification object of a part, from its stored inputs and its current QA / upload state."""
    inputs = part.get("qualification_inputs") if isinstance(part.get("qualification_inputs"), dict) else {}
    technical = [str(i) for i in part.get("technical_issues") or []]
    critical = [str(d.get("type")) for d in part.get("qa_defects") or []
                if isinstance(d, dict) and str(d.get("severity") or "").lower() in {"critical", "high"}]
    qa_pass = (part.get("qa_evidence_recorded") is True and str(part.get("qa_verdict") or "").upper() == "PASS"
               and part.get("qa_passed") is True)
    # The rendered bytes must be hashed: a media-specs digest says nothing about the video content.
    evidence_ok = bool(inputs) and not inputs.get("issues") and part.get("content_sha256_kind") == "bytes"
    publishable = bool(part.get("publishable")) and evidence_ok and qa_pass and not technical and not critical
    if publishable:
        state = "PASS"
    elif not inputs:
        state = "BLOCKED"
    elif part.get("render_ready") is False or technical or not qa_pass:
        state = "FAIL" if (not qa_pass or critical) else "BLOCKED"
    else:
        state = "BLOCKED"
    athlete_group = _digest({"sources": inputs.get("source_shas") or [],
                             "events": sorted(str(e.get("event_uid")) for e in inputs.get("events") or [])})[:24]
    body = {
        "schema": SCHEMA,
        "run_id": os.getenv("PIPELINE_RUN_ID") or part.get("run_id"),
        "pipeline_sha": os.getenv("SPORTREEL_COMMIT") or os.getenv("GITHUB_SHA") or None,
        "source_shas": inputs.get("source_shas") or [],
        "athlete_group_uid": athlete_group,
        "identity": inputs.get("identity") or {"verdict": "UNCERTAIN", "basis": "no_qualification_inputs",
                                               "pairwise_proofs": [], "has_unconfirmed_edges": True},
        "events": inputs.get("events") or [],
        "render": {"content_sha256": part.get("content_sha256"), "content_sha256_kind": part.get("content_sha256_kind"),
                   "edl_digest": part.get("edl_digest"), "media_specs_revision": part.get("media_specs_revision"),
                   "technical_contract_pass": not [i for i in technical if not i.startswith(ISSUE_PREFIX)],
                   "actor_purity_pass": not [i for i in inputs.get("issues") or [] if "interval" in i or "track" in i
                                             or "tail" in i or "lead" in i]},
        "qa": {"final_verdict": part.get("qa_verdict"), "evidence_recorded": part.get("qa_evidence_recorded") is True,
               "critical_defects": critical, "repair_task_ids": list(part.get("repair_task_ids") or [])},
        "blocking": list(dict.fromkeys([*inputs.get("issues", []), *technical])),
        "product_state": state,
        "publishable": publishable,
    }
    body["proof_digest"] = _digest(body)
    return body


def verify(obj: dict[str, Any]) -> bool:
    """A qualification object is intact and publishable only if its digest matches and its own checks agree."""
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA:
        return False
    body = {k: v for k, v in obj.items() if k != "proof_digest"}
    if obj.get("proof_digest") != _digest(body):
        return False
    return (obj.get("publishable") is True and obj.get("product_state") == "PASS" and not obj.get("blocking")
            and obj.get("identity", {}).get("verdict") == "MATCH"
            and all(e.get("eligibility", {}).get("verdict") == VALID for e in obj.get("events") or [])
            and str(obj.get("qa", {}).get("final_verdict") or "").upper() == "PASS"
            and obj.get("render", {}).get("content_sha256_kind") == "bytes")

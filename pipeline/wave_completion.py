"""Wave completion scoring and boundary evidence for REAL-WAVE-002."""
from __future__ import annotations

from typing import Any

SURF_TERMS = {"surf", "surfing", "surfer", "wave", "cutback", "carve", "snap", "ride", "takeoff"}
START_FIELDS = ("ride_start", "takeoff_time", "setup_start")
PEAK_FIELDS = ("peak_time", "action_time", "turn_time", "maneuver_time")
END_FIELDS = ("ride_end", "outcome_end", "landing_time", "exit_time", "kickout_time")
ACTION_TERMS = ("turn", "cutback", "carve", "snap", "maneuver", "bottom turn", "top turn")
OUTCOME_TERMS = ("finish", "complete", "completion", "rides out", "kickout", "kicks out", "lands", "landing", "exits")
REVIEW_THRESHOLD = 0.75


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_id(event: dict[str, Any], index: int = 0) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _text(event: dict[str, Any], sport: str = "") -> str:
    return " ".join([sport, str(event.get("sport", "")), str(event.get("type", "")), str(event.get("description", ""))]).lower()


def is_surf_event(event: dict[str, Any], sport: str = "") -> bool:
    text = _text(event, sport)
    return str(event.get("type", "")).lower() == "surf_ride" or any(term in text for term in SURF_TERMS)


def _time(event: dict[str, Any], fields: tuple[str, ...]) -> tuple[str | None, float | None]:
    for field in fields:
        if event.get(field) is not None:
            return field, _num(event.get(field))
    return None, None


def _window(event: dict[str, Any]) -> tuple[float, float]:
    start = _num(event.get("final_cut_start", event.get("start")))
    end = _num(event.get("final_cut_end", event.get("end")), start)
    return start, end


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def build_wave_boundary_evidence(event: dict[str, Any], sport: str = "") -> dict[str, Any]:
    start, end = _window(event)
    duration = max(0.0, end - start)
    text = _text(event, sport)
    start_field, start_time = _time(event, START_FIELDS)
    peak_field, peak_time = _time(event, PEAK_FIELDS)
    end_field, end_time = _time(event, END_FIELDS)

    start_ev = {"status": "explicit" if start_field else "inferred", "field": start_field, "time": round(start_time if start_time is not None else start, 2), "confidence": 1.0 if start_field else 0.5}
    if peak_field:
        peak_ev = {"status": "explicit", "field": peak_field, "time": round(peak_time or start, 2), "confidence": 1.0}
    elif _has_term(text, ACTION_TERMS):
        peak_ev = {"status": "text_inferred", "field": None, "time": round(start + duration * 0.6, 2), "confidence": 0.65}
    else:
        peak_ev = {"status": "inferred", "field": None, "time": round(start + duration * 0.6, 2), "confidence": 0.5}

    if end_field:
        end_ev = {"status": "explicit", "field": end_field, "time": round(end_time or end, 2), "confidence": 1.0}
    elif event.get("cut_window_evidence_status") == "inferred_tail_padding" and event.get("outcome_end") is not None:
        end_ev = {"status": "tail_inferred", "field": "outcome_end", "time": round(_num(event.get("outcome_end")), 2), "confidence": 0.55}
    elif _has_term(text, OUTCOME_TERMS):
        end_ev = {"status": "text_inferred", "field": None, "time": round(end, 2), "confidence": 0.45}
    else:
        end_ev = {"status": "missing", "field": None, "time": None, "confidence": 0.0}

    outcome_time = end_ev.get("time")
    covers = bool(outcome_time is not None and end + 0.05 >= _num(outcome_time))
    early = bool(outcome_time is not None and end + 0.05 < _num(outcome_time))
    return {
        "schema_version": "1.0",
        "event_id": _event_id(event),
        "ride_start": start_ev,
        "peak_action": peak_ev,
        "ride_end": end_ev,
        "source_window": {"start": round(start, 2), "end": round(end, 2), "duration": round(duration, 2), "covers_outcome": covers, "cut_too_early": early},
        "has_start": True,
        "has_peak": True,
        "has_end": end_ev["status"] != "missing",
    }


def wave_completion_score(evidence: dict[str, Any]) -> float:
    start = _num(evidence.get("ride_start", {}).get("confidence"))
    peak = _num(evidence.get("peak_action", {}).get("confidence"))
    end = _num(evidence.get("ride_end", {}).get("confidence"))
    covers = 1.0 if evidence.get("source_window", {}).get("covers_outcome") else 0.0
    return round(max(0.0, min(1.0, start * 0.2 + peak * 0.3 + end * 0.4 + covers * 0.1)), 2)


def completion_defects(event: dict[str, Any], evidence: dict[str, Any], score: float) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    event_id = evidence.get("event_id") or _event_id(event)
    if evidence.get("source_window", {}).get("cut_too_early"):
        defects.append({"type": "CUT_TOO_EARLY", "defect_type": "CUT_TOO_EARLY", "severity": "critical", "blocking": True, "event_id": event_id, "note": "final cut ends before ride outcome evidence"})
    if not evidence.get("has_end") or score < REVIEW_THRESHOLD:
        defects.append({"type": "WAVE_COMPLETION_UNCERTAIN", "defect_type": "WAVE_COMPLETION_UNCERTAIN", "severity": "critical", "blocking": True, "event_id": event_id, "note": f"wave_completion_score={score}"})
    return defects


def annotate_wave_completion(event: dict[str, Any], sport: str = "") -> dict[str, Any]:
    if not is_surf_event(event, sport):
        return event
    evidence = build_wave_boundary_evidence(event, sport)
    score = wave_completion_score(evidence)
    defects = completion_defects(event, evidence, score)
    out = {**event, "wave_completion_score": score, "wave_boundary_evidence": evidence, "wave_completion_status": "complete" if not defects else "review_required"}
    if defects:
        out["wave_completion_defects"] = defects
        out["dedup_dropped_duplicates"] = [*(out.get("dedup_dropped_duplicates", []) or []), *defects]
        qa_gate = dict(out.get("qa_gate") or {})
        qa_gate["decision"] = qa_gate.get("decision") or "review_required_wave_completion"
        qa_gate["final_verdict"] = "FAIL"
        qa_gate["qa_review_required"] = True
        qa_gate["critical_defect_count"] = max(1, int(qa_gate.get("critical_defect_count") or 0) + len(defects))
        qa_gate["defects"] = [*(qa_gate.get("defects", []) or []), *defects]
        qa_gate["overall"] = qa_gate.get("overall") or "surf ride completion evidence requires operator review"
        out["qa_gate"] = qa_gate
    return out


def annotate_wave_completions(events: list[dict[str, Any]], sport: str = "") -> list[dict[str, Any]]:
    return [annotate_wave_completion(event, sport) if isinstance(event, dict) else event for event in events or []]

"""Tiered QA Gate for compiled reels (OPT-04).

Implements a 3-layer QA architecture that eliminates wasted LLM calls on
deterministically defective renders while strictly preserving the Publishable QA
Contract:

  - Layer 1 (Local Deterministic & CV Pre-Flight):
      Checks resolution, FPS, 9:16 aspect ratio, duration, silent audio state,
      source/time window overlap, athlete identity continuity, tracking evidence,
      and alignment between EDL event windows and the rendered file.
      If Layer 1 fails, the reel is rejected immediately with 0 LLM tokens spent.

  - Layer 2 (Independent Multimodal Content QA + Verified Cache):
      Never approves a reel for publication based solely on Layer 1 technical checks.
      Uses exact SHA-256 QA caching (OPT-07) when the rendered bytes, EDL, identity
      evidence, and QA policy are unchanged; otherwise invokes Gemini content QA.

  - Layer 3 (Exception & Uncertainty Escalation):
      Audits borderline engagement scores, compound minor defects, or low-visibility /
      uncertain identity windows, escalating to strict review when uncertainty is high.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Callable, Mapping

from pipeline.render_qa_cache import (
    compute_qa_signature,
    get_cached_qa_result,
    put_cached_qa_result,
)
from pipeline.silent_output_policy import silent_social_ready_issues

logger = logging.getLogger(__name__)


def _num(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _src_name(ev: Mapping[str, Any]) -> str:
    for k in ("_src", "source", "source_video", "video"):
        v = ev.get(k)
        if v:
            return Path(str(v)).name
    if ev.get("source_person_key"):
        return str(ev["source_person_key"]).split("::")[0]
    return ""


def _event_cut_bounds(ev: Mapping[str, Any]) -> tuple[float, float]:
    s = ev.get("final_cut_start") if ev.get("final_cut_start") is not None else ev.get("start")
    e = ev.get("final_cut_end") if ev.get("final_cut_end") is not None else ev.get("end")
    start = _num(s, 0.0)
    end = _num(e, start)
    return min(start, end), max(start, end)


def run_tier1_local_qa_checks(
    reel_path: str,
    events: list[dict[str, Any]],
    *,
    specs: Mapping[str, Any] | None = None,
    single_reel_per_athlete: bool = False,
) -> dict[str, Any]:
    """Run Layer 1 local deterministic & CV checks before spending LLM tokens."""
    if specs is None:
        try:
            from integrations.ffmpeg import get_reel_specs
            specs = get_reel_specs(reel_path) or {}
        except Exception:
            specs = {}

    effective_specs = dict(specs)
    non_teaser_events = [ev for ev in (events or []) if isinstance(ev, Mapping) and not ev.get("_teaser")]
    if single_reel_per_athlete and len(non_teaser_events) > 1:
        effective_specs["single_reel_per_athlete"] = True

    tech_issues = silent_social_ready_issues(effective_specs)
    fps = _num(effective_specs.get("fps"), 30.0)
    if fps <= 0.0:
        tech_issues.append("invalid_fps")

    defects: list[dict[str, Any]] = []
    for issue in tech_issues:
        defects.append({
            "type": f"TECHNICAL_{issue.upper()}",
            "severity": "critical",
            "at_seconds": 0,
            "note": f"Tier-1 local technical check failed: {issue}",
        })

    # 1. Check duplicate / overlapping source windows within the reel
    seen_windows: list[tuple[str, float, float]] = []
    for ev in non_teaser_events:
        src = _src_name(ev)
        s, e = _event_cut_bounds(ev)
        if e - s < 2.0:
            defects.append({
                "type": "NO_VISIBLE_ACTION",
                "severity": "critical",
                "at_seconds": round(s, 1),
                "note": f"Event window ({s:.1f}s-{e:.1f}s) is shorter than 2.0s minimum action floor.",
            })
        if src:
            for prev_src, ps, pe in seen_windows:
                if src == prev_src:
                    overlap = max(0.0, min(e, pe) - max(s, ps))
                    min_dur = max(0.1, min(e - s, pe - ps))
                    if overlap / min_dur >= 0.50:
                        defects.append({
                            "type": "DUPLICATE_MOMENT",
                            "severity": "critical",
                            "at_seconds": round(s, 1),
                            "note": f"Overlapping source window in {src}: [{s:.1f}s, {e:.1f}s] overlaps [{ps:.1f}s, {pe:.1f}s].",
                        })
                        break
            seen_windows.append((src, s, e))

    # 2. Check athlete identity continuity across events
    athlete_ids = {str(ev.get("athlete_id")) for ev in non_teaser_events if ev.get("athlete_id")}
    if len(athlete_ids) > 1:
        defects.append({
            "type": "IDENTITY_MISMATCH",
            "severity": "critical",
            "at_seconds": 0,
            "note": f"Multiple distinct canonical athlete_ids in one reel: {sorted(athlete_ids)}",
        })

    person_keys_by_src: dict[str, set[str]] = {}
    for ev in non_teaser_events:
        pkey = ev.get("source_person_key")
        if pkey and "::" in str(pkey):
            src_part, pid_part = str(pkey).split("::", 1)
            person_keys_by_src.setdefault(src_part, set()).add(pid_part)
    for src_part, pids in person_keys_by_src.items():
        if len(pids) > 1:
            defects.append({
                "type": "IDENTITY_MISMATCH",
                "severity": "critical",
                "at_seconds": 0,
                "note": f"Multiple distinct persons from the same source video {src_part}: {sorted(pids)}",
            })

    # 3. Check tracking loss / empty windows
    for ev in non_teaser_events:
        if ev.get("perception_evidence_status") == "no_tracker_detection":
            s, _ = _event_cut_bounds(ev)
            defects.append({
                "type": "NO_VISIBLE_ACTION",
                "severity": "critical",
                "at_seconds": round(s, 1),
                "note": "Event lacks CV tracker detection evidence (tracking loss).",
            })

    # 4. Check alignment between EDL events and rendered duration
    duration = _num(effective_specs.get("duration"), 0.0)
    if non_teaser_events and duration > 0.0:
        expected_min = sum(max(0.0, _event_cut_bounds(ev)[1] - _event_cut_bounds(ev)[0]) for ev in non_teaser_events) * 0.35
        if duration < max(3.0, expected_min * 0.4):
            defects.append({
                "type": "PREMATURE_CUT",
                "severity": "critical",
                "at_seconds": round(duration, 1),
                "note": f"Rendered duration ({duration:.1f}s) is severely truncated compared to EDL events.",
            })

    passed = len(defects) == 0 and len(tech_issues) == 0
    return {
        "passed": passed,
        "technical_issues": tech_issues,
        "defects": defects,
        "specs": effective_specs,
    }


def run_tier3_exception_audit(
    qa_result: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    engagement_threshold: int = 60,
) -> dict[str, Any]:
    """Layer 3 exception audit for borderline scores, compound minor defects, or low-visibility windows."""
    result = dict(qa_result)
    defects = [dict(d) for d in (result.get("defects") or []) if isinstance(d, Mapping)]
    score = int(_num(result.get("engagement_score"), 0))
    non_teaser = [ev for ev in (events or []) if isinstance(ev, Mapping) and not ev.get("_teaser")]

    minor_defects = [d for d in defects if str(d.get("severity") or "").lower() == "minor"]
    low_vis_events = [
        ev for ev in non_teaser
        if ev.get("visible_ratio") is not None and _num(ev.get("visible_ratio"), 1.0) < 0.015
    ]
    borderline_score = engagement_threshold <= score < (engagement_threshold + 6)

    escalated = False
    escalation_reasons: list[str] = []
    if len(minor_defects) >= 3:
        escalated = True
        escalation_reasons.append("compound_minor_defects_exceed_limit")
    if borderline_score and len(minor_defects) >= 2:
        escalated = True
        escalation_reasons.append("borderline_score_with_multiple_minor_defects")
    if low_vis_events and borderline_score:
        escalated = True
        escalation_reasons.append("low_athlete_visibility_with_borderline_engagement")

    if escalated and result.get("verdict") == "PASS":
        defects.append({
            "type": "TIER3_EXCEPTION_REVIEW_REQUIRED",
            "severity": "critical",
            "at_seconds": 0,
            "note": f"Tier-3 exception escalation blocked auto-approval: {', '.join(escalation_reasons)}",
        })
        result["verdict"] = "FAIL"
        result["defects"] = defects
        result["overall"] = f"{result.get('overall', '')} [Escalated by Tier-3 exception audit: {', '.join(escalation_reasons)}]".strip()

    result["tier3_exception_audit"] = {
        "escalated": escalated,
        "reasons": escalation_reasons,
        "minor_defect_count": len(minor_defects),
        "low_visibility_event_count": len(low_vis_events),
    }
    return result


def evaluate_reel_tiered_qa(
    reel_path: str,
    *,
    events: list[dict[str, Any]] | None = None,
    sport: str = "",
    athlete_label: str = "",
    content_qa_fn: Callable[[str, str, str], dict[str, Any]],
    specs: Mapping[str, Any] | None = None,
    engagement_threshold: int = 60,
    single_reel_per_athlete: bool = True,
) -> dict[str, Any]:
    """Execute the full 3-tier QA pipeline for a compiled reel while preserving the Publishable QA Contract."""
    event_list = list(events or [])
    tier1 = run_tier1_local_qa_checks(
        reel_path,
        event_list,
        specs=specs,
        single_reel_per_athlete=single_reel_per_athlete,
    )
    if not tier1["passed"]:
        return {
            "verdict": "FAIL",
            "technical": {
                "pass": False,
                "issues": tier1["technical_issues"],
                **tier1["specs"],
            },
            "content": {},
            "defects": tier1["defects"],
            "engagement_score": 0,
            "overall": "Rejected by Tier-1 local deterministic QA check (0 LLM tokens used).",
            "qa_tier": "tier1_local_reject",
            "llm_called": False,
        }

    # Layer 2: Check deterministic QA cache (bound to exact file SHA-256 + EDL + identity + policy)
    qa_sig = compute_qa_signature(
        reel_path,
        events=event_list,
        sport=sport,
        athlete_label=athlete_label,
    )
    cached = get_cached_qa_result(qa_sig)
    if cached is not None:
        audited = run_tier3_exception_audit(cached, event_list, engagement_threshold=engagement_threshold)
        audited["qa_tier"] = "tier2_cached_content_qa"
        audited["llm_called"] = False
        return audited

    # Layer 2: Independent multimodal content QA via Gemini (mandatory for publishable approval)
    raw_result = content_qa_fn(reel_path, sport, athlete_label)
    if not isinstance(raw_result, dict):
        raw_result = {}

    audited = run_tier3_exception_audit(raw_result, event_list, engagement_threshold=engagement_threshold)
    audited["qa_tier"] = "tier2_live_content_qa"
    audited["llm_called"] = True
    if qa_sig is not None:
        put_cached_qa_result(qa_sig, audited)
    return audited


__all__ = [
    "evaluate_reel_tiered_qa",
    "run_tier1_local_qa_checks",
    "run_tier3_exception_audit",
]

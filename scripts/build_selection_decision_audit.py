#!/usr/bin/env python3
"""Build an operator-readable selection decision audit.

The existing candidate ledger records which selector candidates were selected or
not emitted. This script turns that raw ledger into product telemetry that can
answer questions such as:

- Why did one wave make the draft while other apparent waves did not?
- Was a candidate dropped by the analyzer, source-window dedup, or long-video
  subject prefilter?
- Are similar person descriptions likely fragments of the same athlete identity?

The output is intentionally JSON-first so it can be stored with every pipeline
artifact and later loaded into Supabase/BI/Obsidian without scraping logs.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sportreel.selection_decision_audit.v1"

_SHARED_WINDOW_TERMS = (
    "shared wave",
    "shares a wave",
    "party wave",
    "same wave",
    "another rider",
    "another surfer",
    "other rider",
    "other surfer",
    "partially obstructed",
    "obstructed by",
    "crowded",
    "multiple surfers",
    "multiple riders",
)

_STOPWORDS = {
    "a", "an", "and", "the", "in", "on", "of", "with", "to", "for", "from",
    "surfer", "rider", "athlete", "person", "draft", "reel", "mp4", "one", "piece",
    "swimsuit", "trunks", "shorts", "long", "sleeved",
}

_COLOR_OR_EQUIPMENT = {
    "black", "dark", "white", "red", "pink", "brown", "blue", "green", "yellow",
    "turquoise", "lilac", "orange", "longboard", "shortboard", "board", "wetsuit",
    "bikini", "shirt", "swimsuit", "trunks", "shorts",
}


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _tokens(text: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _similarity(a: Any, b: Any) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / len(ta | tb), 3)


def _equipment_overlap(a: Any, b: Any) -> list[str]:
    return sorted((_tokens(a) & _tokens(b)) & _COLOR_OR_EQUIPMENT)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _window(candidate: dict[str, Any]) -> dict[str, Any]:
    window = candidate.get("source_window") if isinstance(candidate.get("source_window"), dict) else {}
    start = _safe_float(window.get("start"))
    end = _safe_float(window.get("end"))
    duration = _safe_float(window.get("duration"))
    if duration is None and start is not None and end is not None:
        duration = round(end - start, 2)
    return {"start": start, "end": end, "duration": duration}


def _time_gap_seconds(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    wa = _window(a)
    wb = _window(b)
    if wa["start"] is None or wa["end"] is None or wb["start"] is None or wb["end"] is None:
        return None
    if wa["end"] < wb["start"]:
        return round(wb["start"] - wa["end"], 2)
    if wb["end"] < wa["start"]:
        return round(wa["start"] - wb["end"], 2)
    return 0.0


def _shared_window_flags(candidate: dict[str, Any]) -> list[str]:
    text = str(candidate.get("description") or "").lower()
    return [term for term in _SHARED_WINDOW_TERMS if term in text]


def _parse_pre_qa_log(log_path: Path | None) -> dict[str, dict[str, Any]]:
    if not log_path or not log_path.exists():
        return {}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict[str, Any]] = {}
    skipped_re = re.compile(r"Pre-QA skipped (\d+) subject-gated event\(s\) for (.+)")
    no_clean_re = re.compile(r"No clean single-athlete events for (.+?) — no draft uploaded")
    for line in text.splitlines():
        match = skipped_re.search(line)
        if match:
            description = match.group(2).strip()
            entry = out.setdefault(description, {"subject_gated_event_count": 0, "no_clean_single_athlete_events": False, "evidence_lines": []})
            entry["subject_gated_event_count"] += int(match.group(1))
            entry["evidence_lines"].append(line.strip())
        match = no_clean_re.search(line)
        if match:
            description = match.group(1).strip()
            entry = out.setdefault(description, {"subject_gated_event_count": 0, "no_clean_single_athlete_events": False, "evidence_lines": []})
            entry["no_clean_single_athlete_events"] = True
            entry["evidence_lines"].append(line.strip())
    return out


def _find_prefilter_evidence(candidate: dict[str, Any], preqa: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    desc = str(candidate.get("person_description") or "").strip()
    if desc in preqa:
        return preqa[desc]
    best_desc = ""
    best_score = 0.0
    for logged_desc in preqa:
        score = _similarity(desc, logged_desc)
        if score > best_score:
            best_score = score
            best_desc = logged_desc
    if best_score >= 0.72:
        evidence = dict(preqa[best_desc])
        evidence["matched_logged_person_description"] = best_desc
        evidence["person_description_similarity"] = best_score
        return evidence
    return None


def _candidate_stage_and_reason(candidate: dict[str, Any], preqa: dict[str, dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    evidence: dict[str, Any] = {}
    if candidate.get("selected"):
        return "uploaded_draft", "selected_for_uploaded_draft", evidence

    raw_cause = str(candidate.get("discard_cause") or "")
    shared_flags = _shared_window_flags(candidate)
    if shared_flags:
        evidence["description_shared_window_terms"] = shared_flags

    if raw_cause == "selected_by_selector_not_emitted_as_draft":
        preqa_evidence = _find_prefilter_evidence(candidate, preqa)
        if preqa_evidence:
            evidence["pre_qa_prefilter"] = preqa_evidence
            return "long_video_pre_qa_prefilter", "subject_gated_by_pre_qa_prefilter", evidence
        if shared_flags:
            return "single_athlete_selection_policy", "shared_or_obstructed_window", evidence
        return "post_selector_not_emitted", "selected_by_selector_not_emitted_as_draft", evidence

    if raw_cause in {"fragment_shorter_than_min_event_sec", "score_below_selection_threshold", "dedup_overlap_lower_score"}:
        return "selector", raw_cause, evidence

    if raw_cause:
        return "unknown_pipeline_stage", raw_cause, evidence
    return "unknown_pipeline_stage", "missing_discard_cause", evidence


def _candidate_ref(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id"),
        "person_id": candidate.get("person_id"),
        "person_description": candidate.get("person_description"),
        "draft_name": candidate.get("draft_name"),
        "selected": bool(candidate.get("selected")),
        "discarded": bool(candidate.get("discarded")),
        "event_type": candidate.get("event_type"),
        "score": candidate.get("score"),
        "source_video": candidate.get("source_video"),
        "source_window": _window(candidate),
        "description": candidate.get("description"),
    }


def _enrich_candidates(candidates: list[dict[str, Any]], preqa: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        stage, reason, evidence = _candidate_stage_and_reason(candidate, preqa)
        row = _candidate_ref(candidate)
        row.update({
            "discard_stage": stage if row["discarded"] else None,
            "discard_cause_detailed": reason if row["discarded"] else None,
            "selection_stage": stage if row["selected"] else None,
            "selection_reason_detailed": reason if row["selected"] else None,
            "evidence": evidence,
        })
        enriched.append(row)
    return enriched


def _person_summary(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        key = str(row.get("person_description") or row.get("person_id") or "unknown")
        by_person[key].append(row)
    out = []
    for person, rows in sorted(by_person.items()):
        selected = [row for row in rows if row.get("selected")]
        discarded = [row for row in rows if row.get("discarded")]
        out.append({
            "person_description": person,
            "candidate_count": len(rows),
            "selected_count": len(selected),
            "discarded_count": len(discarded),
            "discard_stage_counts": dict(Counter(row.get("discard_stage") or "selected" for row in rows)),
            "discard_cause_counts": dict(Counter(row.get("discard_cause_detailed") or "selected" for row in rows)),
            "score_max": max((row.get("score") or 0 for row in rows), default=0),
            "selected_windows": [_candidate_ref(row) for row in selected],
            "discarded_windows": [_candidate_ref(row) for row in discarded],
        })
    return out


def _draft_label(draft: dict[str, Any]) -> str:
    return str(draft.get("draft_name") or draft.get("draft_id") or "unknown_draft")


def _draft_tokens(draft_name: str) -> str:
    base = re.sub(r"^DRAFT_", "", draft_name)
    base = re.sub(r"_20\d{6}.*$", "", base)
    base = base.replace("_", " ")
    return base


def _related_score(candidate: dict[str, Any], draft_name: str, selected_candidate: dict[str, Any] | None) -> tuple[float, dict[str, Any]]:
    draft_desc = _draft_tokens(draft_name)
    cand_desc = candidate.get("person_description") or ""
    sim_to_draft = _similarity(cand_desc, draft_desc)
    equip = _equipment_overlap(cand_desc, draft_desc)
    time_gap = None
    sim_to_selected = 0.0
    if selected_candidate:
        sim_to_selected = _similarity(cand_desc, selected_candidate.get("person_description") or selected_candidate.get("description") or "")
        time_gap = _time_gap_seconds(candidate, selected_candidate)
    score = sim_to_draft + (0.15 * len(equip)) + (sim_to_selected * 0.5)
    if time_gap is not None and time_gap <= 60:
        score += 0.25
    return round(score, 3), {
        "similarity_to_draft_label": sim_to_draft,
        "similarity_to_selected_candidate": sim_to_selected,
        "shared_color_or_equipment_tokens": equip,
        "time_gap_seconds": time_gap,
    }


def _draft_audits(trace: dict[str, Any], enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drafts = [draft for draft in trace.get("drafts", []) if isinstance(draft, dict)]
    out = []
    selected_rows = [row for row in enriched if row.get("selected")]
    for draft in drafts:
        draft_name = _draft_label(draft)
        selected_for_draft = [row for row in selected_rows if row.get("draft_name") == draft_name or row.get("draft_name") is None]
        selected_anchor = selected_for_draft[0] if selected_for_draft else None
        related = []
        for candidate in enriched:
            if candidate.get("selected") and candidate.get("draft_name") == draft_name:
                continue
            score, evidence = _related_score(candidate, draft_name, selected_anchor)
            if score >= 0.45:
                related.append({
                    **candidate,
                    "relatedness_score": score,
                    "relatedness_evidence": evidence,
                    "possible_identity_fragmentation": bool(candidate.get("discarded") and (score >= 0.9 or len(evidence.get("shared_color_or_equipment_tokens", [])) >= 2)),
                })
        related.sort(key=lambda item: (item.get("possible_identity_fragmentation", False), item.get("score") or 0, item.get("relatedness_score") or 0), reverse=True)
        out.append({
            "draft_id": draft.get("draft_id"),
            "draft_name": draft_name,
            "sport": draft.get("sport"),
            "selected_wave_count": len(draft.get("source_windows") or draft.get("events") or []),
            "selected_windows": draft.get("source_windows") or [],
            "related_unselected_candidate_count": len([row for row in related if row.get("discarded")]),
            "possible_identity_fragmentation_count": len([row for row in related if row.get("possible_identity_fragmentation")]),
            "top_related_unselected_candidates": related[:10],
        })
    return out


def build_audit(ledger_path: Path, trace_path: Path, log_path: Path | None = None) -> dict[str, Any]:
    ledger = _read_json(ledger_path)
    trace = _read_json(trace_path)
    preqa = _parse_pre_qa_log(log_path)
    raw_candidates = [item for item in ledger.get("candidates", []) if isinstance(item, dict)]
    enriched = _enrich_candidates(raw_candidates, preqa)
    draft_audits = _draft_audits(trace, enriched)
    discard_stage_counts = Counter(row.get("discard_stage") for row in enriched if row.get("discarded"))
    discard_cause_counts = Counter(row.get("discard_cause_detailed") for row in enriched if row.get("discarded"))
    possible_identity_fragmentation_count = sum(
        draft.get("possible_identity_fragmentation_count", 0) for draft in draft_audits
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "candidate_decision_ledger_path": str(ledger_path),
            "candidate_decision_ledger_schema_version": ledger.get("schema_version"),
            "draft_decision_trace_path": str(trace_path),
            "draft_decision_trace_schema_version": trace.get("schema_version"),
            "log_path": str(log_path) if log_path else None,
        },
        "summary": {
            "candidate_count": len(enriched),
            "selected_count": sum(1 for row in enriched if row.get("selected")),
            "discarded_count": sum(1 for row in enriched if row.get("discarded")),
            "discard_stage_counts": dict(discard_stage_counts),
            "discard_cause_counts": dict(discard_cause_counts),
            "draft_count": len(draft_audits),
            "possible_identity_fragmentation_count": possible_identity_fragmentation_count,
            "selection_reason_coverage": "stage_and_reason_per_candidate" if enriched else "no_candidates",
        },
        "drafts": draft_audits,
        "persons": _person_summary(enriched),
        "candidates": enriched,
    }


def main() -> int:
    if len(sys.argv) not in {4, 5}:
        print("usage: build_selection_decision_audit.py CANDIDATE_LEDGER_JSON DRAFT_DECISION_TRACE_JSON OUTPUT_JSON [RUN_LOG]", file=sys.stderr)
        return 2
    ledger_path = Path(sys.argv[1])
    trace_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])
    log_path = Path(sys.argv[4]) if len(sys.argv) == 5 else None
    audit = build_audit(ledger_path, trace_path, log_path)
    _write_json(output_path, audit)
    summary = audit["summary"]
    print(
        "selection decision audit "
        f"candidates={summary['candidate_count']} "
        f"selected={summary['selected_count']} "
        f"discarded={summary['discarded_count']} "
        f"identity_fragmentation={summary['possible_identity_fragmentation_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

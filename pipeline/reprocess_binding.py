"""Bind a reprocess request to one athlete, one output part and its defects; judge the repair against that binding.

Athlete ids are run-local (`ath_…`, `athlete_…`), so no id survives into the run that performs the repair. The
binding therefore anchors the athlete in the footage itself: for each shot of the original output part it keeps the
canonical event id, the source content reference (`sha256:<hex>`), the analyzer window, the action type and the
source-local tracker id of the target actor (`publishable_reel_policy._action_evidence`).

Binding modes (recorded in every verdict):

* `athlete_and_output_bound` - a valid binding; the only mode that can ever close a request as `done`.
* `binding_missing`          - the QA gate (or the operator API) created the task but could not bind it.
* `binding_invalid`          - `target_athlete_key` is present but not a valid binding.
* `binding_stale`            - the binding names another draft or another output revision than the request row.
* `legacy_explicit`          - a historical row created before bindings existed (no binding columns at all).
  It is never closed as `done` automatically: its repair is routed to manual reconciliation.

Matching (identity-safe): an action of the repair run supports an original action only on the same source
*content* (equal `sha256:` reference; a shared file name is not enough).

* STRONG: same canonical event id, or the same source-local track id with overlap >= half the shorter window.
* MEDIUM: temporal IoU >= 0.5 and a compatible action type, with no track evidence against it.
* CONTRADICTION: overlap >= half the shorter window but both tracks known and different (another actor).

A row is the target only if it has no contradiction and either a STRONG link, MEDIUM links to at least two
different original actions, or one MEDIUM link when the original part had a single action. Any other row that
also qualifies, or that substantially overlaps without being excluded by track evidence, makes the match
ambiguous. Nothing else is a match: the request stays unverified.

Output: the repair must be the part(s) of the target row whose shots link to the original part, each with a real
byte SHA-256 (not a media-specs digest) that differs from the original, publishable (final QA PASS recorded, no
technical issue, uploaded, authority persisted) and carrying none of the requested defect types.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

BINDING_VERSION = 2

MODE_BOUND = "athlete_and_output_bound"
MODE_MISSING = "binding_missing"
MODE_INVALID = "binding_invalid"
MODE_STALE = "binding_stale"
MODE_LEGACY = "legacy_explicit"

# Kept for readers of verdicts written by earlier code; the basis is now the binding mode.
BASIS_BOUND = MODE_BOUND
BASIS_LEGACY = MODE_LEGACY

MEDIUM_IOU = 0.5
SUPPORT_FRACTION = 0.5  # of the shorter window, for STRONG track links, contradictions and competitors
_RIDE_TYPES = {"wave_catch", "ride", "wave", "surf", "surfing", "turn", "cutback", "maneuver", "barrel",
               "bottom_turn", "top_turn", "carve", "trick", "highlight", "action"}


def _base(source: Any) -> str:
    return os.path.basename(str(source or "").strip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- binding creation

def find_draft_part(manifest: dict[str, Any], draft_name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The manifest row and part uploaded under `draft_name`, only if exactly one matches."""
    matches = [
        (row, part)
        for row in (manifest or {}).get("athletes", []) or [] if isinstance(row, dict)
        for part in row.get("parts", []) or [] if isinstance(part, dict)
        if draft_name and draft_name in {part.get("review_draft_name"), part.get("file_name")}
    ]
    return matches[0] if len(matches) == 1 else None


def _valid_action(action: Any) -> dict[str, Any] | None:
    if not isinstance(action, dict):
        return None
    ref = str(action.get("source_ref") or "")
    try:
        start, end = float(action.get("start")), float(action.get("end"))
    except (TypeError, ValueError):
        return None
    if not ref.startswith("sha256:") or len(ref) < 20 or not end > start:
        return None
    return {"event_uid": action.get("event_uid") or None, "source": _base(action.get("source")) or None,
            "source_ref": ref, "start": round(start, 3), "end": round(end, 3),
            "type": (str(action.get("type")).lower() if action.get("type") else None),
            "track": (str(action.get("track")) if action.get("track") not in (None, "") else None)}


def missing_marker(draft_name: str, reason: str, run_id: str | None = None) -> dict[str, Any]:
    """Columns for a task that could not be bound: an explicit marker, never an empty key."""
    return {"target_athlete_key": json.dumps({"v": BINDING_VERSION, "mode": MODE_MISSING, "reason": reason,
                                              "draft_name": draft_name, "run_id": run_id},
                                             sort_keys=True, separators=(",", ":")),
            "original_output_sha256": None}


def build_binding(manifest: dict[str, Any], draft_name: str, *, defect_types: list[str] | None = None,
                  run_id: str | None = None) -> dict[str, Any]:
    """Columns for a new QA task: a valid binding, or an explicit `binding_missing` marker with its reason."""
    found = find_draft_part(manifest, draft_name)
    if not found:
        return missing_marker(draft_name, "draft_not_uniquely_in_manifest", run_id)
    row, part = found
    if part.get("content_sha256_kind") != "bytes" or not str(part.get("content_sha256") or "").strip():
        return missing_marker(draft_name, "output_bytes_hash_unknown", run_id)
    actions = [a for a in (_valid_action(x) for x in part.get("action_evidence") or []) if a]
    if not actions or len(actions) != len(part.get("action_evidence") or []):
        return missing_marker(draft_name, "action_evidence_incomplete", run_id)
    sha = str(part["content_sha256"]).strip()
    key = {
        "v": BINDING_VERSION, "mode": MODE_BOUND, "run_id": run_id, "draft_name": draft_name,
        "run_athlete_key": row.get("athlete_key"), "part_index": part.get("part_index"),
        "output_sha256": sha, "source_refs": sorted({a["source_ref"] for a in actions}),
        "defect_types": sorted({str(d).upper() for d in defect_types or []}), "actions": actions,
    }
    return {"target_athlete_key": json.dumps(key, sort_keys=True, separators=(",", ":")),
            "original_output_sha256": sha}


# ---------------------------------------------------------------- binding classification

def classify_binding(request: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str]:
    """(mode, binding, detail) for a request row."""
    text = request.get("target_athlete_key")
    if text in (None, "") and not request.get("original_output_sha256"):
        return MODE_LEGACY, None, "no_binding_columns"
    try:
        data = json.loads(str(text)) if text else None
    except (TypeError, ValueError):
        return MODE_INVALID, None, "not_json"
    if not isinstance(data, dict):
        return MODE_INVALID, None, "not_an_object"
    if data.get("v") != BINDING_VERSION:
        return MODE_INVALID, None, f"unsupported_version:{data.get('v')}"
    if data.get("mode") == MODE_MISSING:
        return MODE_MISSING, None, str(data.get("reason") or "unspecified")
    if data.get("mode") != MODE_BOUND:
        return MODE_INVALID, None, f"unknown_mode:{data.get('mode')}"
    raw = data.get("actions") if isinstance(data.get("actions"), list) else []
    actions = [a for a in (_valid_action(x) for x in raw) if a]
    if not actions or len(actions) != len(raw):
        return MODE_INVALID, None, "invalid_actions"
    sha = str(data.get("output_sha256") or "")
    if len(sha) != 64:
        return MODE_INVALID, None, "invalid_output_sha256"
    if data.get("draft_name") != request.get("draft_name"):
        return MODE_STALE, None, "binding_names_another_draft"
    if sha != str(request.get("original_output_sha256") or ""):
        return MODE_STALE, None, "binding_names_another_output_revision"
    return MODE_BOUND, {**data, "actions": actions}, ""


# ---------------------------------------------------------------- matching

def _iou(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float]:
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if inter <= 0:
        return 0.0, 0.0
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    shorter = min(a["end"] - a["start"], b["end"] - b["start"])
    return inter / union, inter / shorter


def _types_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ta, tb = a.get("type"), b.get("type")
    return not ta or not tb or ta == tb or (ta in _RIDE_TYPES and tb in _RIDE_TYPES)


def link(original: dict[str, Any], candidate: dict[str, Any]) -> str:
    """STRONG / MEDIUM / WEAK / CONTRADICTION / NONE between one original and one repair action."""
    if original["source_ref"] != candidate["source_ref"]:
        return "NONE"
    if original.get("event_uid") and original["event_uid"] == candidate.get("event_uid"):
        return "STRONG"
    iou, support = _iou(original, candidate)
    if support <= 0:
        return "NONE"
    tracks_known = bool(original.get("track")) and bool(candidate.get("track"))
    if tracks_known and support >= SUPPORT_FRACTION:
        return "STRONG" if original["track"] == candidate["track"] else "CONTRADICTION"
    if iou >= MEDIUM_IOU and _types_compatible(original, candidate):
        return "MEDIUM"
    return "WEAK" if support >= SUPPORT_FRACTION else "NONE"


def _part_actions(part: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in (_valid_action(x) for x in part.get("action_evidence") or []) if a]


def _row_links(row: dict[str, Any], originals: list[dict[str, Any]]) -> dict[str, Any]:
    strong, medium, weak, contra = set(), set(), set(), set()
    linked_parts: set[int] = set()
    for index, part in enumerate(p for p in row.get("parts", []) or [] if isinstance(p, dict)):
        for candidate in _part_actions(part):
            for i, original in enumerate(originals):
                kind = link(original, candidate)
                {"STRONG": strong, "MEDIUM": medium, "WEAK": weak, "CONTRADICTION": contra}.get(kind, set()).add(i)
                if kind in {"STRONG", "MEDIUM"}:
                    linked_parts.add(index)
    qualifies = not contra and (bool(strong) or len(medium) >= 2 or (len(medium) == 1 and len(originals) == 1))
    competitor = not qualifies and not contra and bool(strong | medium | weak)
    return {"qualifies": qualifies, "competitor": competitor, "contradiction": bool(contra),
            "strong": sorted(strong), "medium": sorted(medium), "linked_parts": sorted(linked_parts)}


def match_target(binding: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    """(row, reason, evidence) for the bound athlete in the repair run's manifest."""
    originals = binding["actions"]
    scored = [(row, _row_links(row, originals)) for row in (manifest or {}).get("athletes", []) or []
              if isinstance(row, dict)]
    qualifying = [(row, ev) for row, ev in scored if ev["qualifies"]]
    competitors = [(row, ev) for row, ev in scored if ev["competitor"]]
    contradicted = [(row, ev) for row, ev in scored if ev["contradiction"]]
    summary = {"qualifying": len(qualifying), "competitors": len(competitors), "contradicted": len(contradicted)}
    if len(qualifying) == 1 and not competitors:
        row, ev = qualifying[0]
        return row, "", {**summary, **ev}
    if len(qualifying) > 1 or (qualifying and competitors):
        return None, "target_athlete_ambiguous", summary
    if competitors or contradicted:
        return None, "identity_unverified", summary
    return None, "target_athlete_not_found", summary


# ---------------------------------------------------------------- judgement

def part_defect_types(part: dict[str, Any]) -> set[str]:
    codes = {str(d.get("type")).upper() for d in part.get("qa_defects") or [] if isinstance(d, dict) and d.get("type")}
    for reason in [*(part.get("qa_gate_block_reasons") or []), *(part.get("technical_issues") or [])]:
        codes.add(str(reason).split(":", 1)[0].strip().upper())
    return codes


def judge(request: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Verdict for one re-queued request: {verified, binding_mode, reason, ...}, written to `repair_verdict`."""
    wanted = {str(code).upper() for code in request.get("defect_types") or []}
    mode, binding, detail = classify_binding(request)
    verdict: dict[str, Any] = {"binding_mode": mode, "basis": mode, "checked_at": _now(),
                               "original_output_sha256": request.get("original_output_sha256") or None,
                               "repair_output_sha256": None, "remaining_defects": []}
    if mode == MODE_LEGACY:
        return {**verdict, "verified": False, "reason": "legacy_manual_reconciliation_required"}
    if mode != MODE_BOUND:
        return {**verdict, "verified": False, "reason": mode, "binding_detail": detail}

    row, reason, evidence = match_target(binding, manifest)
    verdict.update({"original_run_athlete_key": binding.get("run_athlete_key"), "match": evidence})
    if row is None:
        return {**verdict, "verified": False, "reason": reason}
    parts = [p for p in row.get("parts", []) or [] if isinstance(p, dict)]
    linked = [parts[i] for i in evidence.get("linked_parts", []) if i < len(parts)]
    original = binding["output_sha256"]
    shas = [str(p.get("content_sha256") or "") for p in linked]
    remaining = sorted(set().union(*(wanted & part_defect_types(p) for p in linked))) if linked else []
    if not linked:
        reason = "repaired_part_not_identified"
    elif any(p.get("content_sha256_kind") != "bytes" or len(s) != 64 for p, s in zip(linked, shas)):
        reason = "repair_output_hash_not_bytes"
    elif any(s == original for s in shas):
        reason = "output_unchanged"
    elif remaining:
        reason = "remaining_defects"
    elif not all(p.get("publishable") is True for p in linked):
        reason = "not_publishable"
    elif not all(str(p.get("qa_verdict") or "").upper() == "PASS" and p.get("qa_evidence_recorded") is True
                 for p in linked):
        reason = "final_qa_not_passed"
    else:
        reason = ""
    return {**verdict, "verified": not reason, "reason": reason, "repair_athlete_key": row.get("athlete_key"),
            "repair_part_indexes": [p.get("part_index") for p in linked], "remaining_defects": remaining,
            "repair_output_sha256": shas[0] if len(shas) == 1 else (",".join(shas) or None)}

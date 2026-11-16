"""Bind a reprocess request to one athlete and one output, and judge its repair against that binding.

Athlete ids in this pipeline are run-local (`ath_…` from canonicalization, `athlete_…` in the manifest), so no id
survives into the run that performs the repair. What does survive is the footage: the source files and the time
windows the athlete acted in. A request is therefore bound, when its QA task is created, to

* `target_athlete_key` - a versioned JSON binding: the original run's athlete key (for tracing only) and the
  athlete's actions as `[source basename, start, end, type]`;
* `original_output_sha256` - the content hash of the draft the request was opened on.

In the repair run the target athlete is the single manifest row with an action on the same source that overlaps
one of the original actions. No such row, or more than one, is not a match. The request is `done` only when that
athlete's reel is publishable, carries none of the defect types the request was opened for, and is a different
output (its content hash differs from the original). Requests without a binding (older rows, operator requests
created outside the QA gate) keep the conservative source-wide rule, and their verdict says so.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

BINDING_VERSION = 1
MIN_OVERLAP_FRACTION = 0.3  # of the shorter window

BASIS_BOUND = "athlete_and_output_bound"
BASIS_LEGACY = "source_wide_legacy"


def _base(source: Any) -> str:
    return os.path.basename(str(source or "").strip())


def _lineage_actions(row: dict[str, Any]) -> list[list[Any]]:
    actions: list[list[Any]] = []
    for item in row.get("action_lineage") or []:
        parts = str(item).split("|")
        if len(parts) < 4:
            continue
        try:
            start, end = float(parts[1]), float(parts[2])
        except ValueError:
            continue
        if end > start and _base(parts[0]):
            actions.append([_base(parts[0]), round(start, 3), round(end, 3), parts[3]])
    return actions


def find_draft_part(manifest: dict[str, Any], draft_name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The manifest row and part uploaded under `draft_name`, only if exactly one matches."""
    matches = [
        (row, part)
        for row in (manifest or {}).get("athletes", []) or [] if isinstance(row, dict)
        for part in row.get("parts", []) or [] if isinstance(part, dict)
        if draft_name and draft_name in {part.get("review_draft_name"), part.get("file_name")}
    ]
    return matches[0] if len(matches) == 1 else None


def build_binding(manifest: dict[str, Any], draft_name: str) -> dict[str, Any]:
    """Columns to store on a new QA task: `target_athlete_key` and `original_output_sha256`, or {} if unknown."""
    found = find_draft_part(manifest, draft_name)
    if not found:
        return {}
    row, part = found
    actions = _lineage_actions(row)
    sha = str(part.get("content_sha256") or "").strip()
    if not actions or not sha:
        return {}
    key = json.dumps({"v": BINDING_VERSION, "run_athlete_key": row.get("athlete_key"), "actions": actions},
                     sort_keys=True, separators=(",", ":"))
    return {"target_athlete_key": key, "original_output_sha256": sha}


def parse_binding(text: Any) -> dict[str, Any] | None:
    """The binding stored in `target_athlete_key`, or None when absent or not a valid v1 binding."""
    if not text:
        return None
    try:
        data = json.loads(str(text))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != BINDING_VERSION or not isinstance(data.get("actions"), list):
        return None
    actions = []
    for action in data["actions"]:
        if (isinstance(action, list) and len(action) >= 3 and _base(action[0])
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in action[1:3])
                and action[2] > action[1]):
            actions.append([_base(action[0]), float(action[1]), float(action[2])])
    if not actions:
        return None
    return {"run_athlete_key": data.get("run_athlete_key"), "actions": actions}


def _overlaps(a: list[Any], b: list[Any]) -> bool:
    if a[0] != b[0]:
        return False
    inter = min(a[2], b[2]) - max(a[1], b[1])
    shorter = min(a[2] - a[1], b[2] - b[1])
    return inter > 0 and shorter > 0 and inter >= MIN_OVERLAP_FRACTION * shorter


def match_target(binding: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """The repair run's row for the bound athlete, and why when there is none."""
    candidates = [
        row for row in (manifest or {}).get("athletes", []) or [] if isinstance(row, dict)
        if any(_overlaps(new, old) for new in _lineage_actions(row) for old in binding["actions"])
    ]
    if not candidates:
        return None, "target_athlete_not_found"
    if len(candidates) > 1:
        return None, "target_athlete_ambiguous"
    return candidates[0], ""


def part_defect_types(part: dict[str, Any]) -> set[str]:
    codes = {str(d.get("type")).upper() for d in part.get("qa_defects") or [] if isinstance(d, dict) and d.get("type")}
    for reason in [*(part.get("qa_gate_block_reasons") or []), *(part.get("technical_issues") or [])]:
        codes.add(str(reason).split(":", 1)[0].strip().upper())
    return codes


def _row_state(row: dict[str, Any]) -> tuple[bool, set[str], list[dict[str, Any]]]:
    parts = [part for part in row.get("parts", []) or [] if isinstance(part, dict)]
    ok = bool(row.get("primary_publishable_reel")) and bool(parts) and all(part.get("publishable") is True for part in parts)
    defects: set[str] = set()
    for part in parts:
        defects |= part_defect_types(part)
    return ok, defects, parts


def _primary_sha(row: dict[str, Any], parts: list[dict[str, Any]]) -> str:
    primary = str(row.get("primary_publishable_reel") or "")
    for part in parts:
        if primary and primary in {str(part.get("local_path") or ""), str(part.get("review_draft_name") or ""),
                                   str(part.get("file_name") or ""), _base(part.get("local_path"))}:
            return str(part.get("content_sha256") or "")
    return str(parts[0].get("content_sha256") or "") if len(parts) == 1 else ""


def judge(request: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Verdict for one re-queued request: {verified, basis, reason, ...} - written to `repair_verdict`."""
    wanted = {str(code).upper() for code in request.get("defect_types") or []}
    checked_at = datetime.now(timezone.utc).isoformat()
    binding = parse_binding(request.get("target_athlete_key"))
    if binding is None:
        names = {_base(name) for name in request.get("sources") or []}
        rows = [row for row in (manifest or {}).get("athletes", []) or [] if isinstance(row, dict)
                and any(action[0] in names for action in _lineage_actions(row))]
        states = [_row_state(row) for row in rows]
        remaining = sorted(set().union(*(wanted & d for _, d, _ in states))) if states else []
        verified = bool(states) and all(ok for ok, _, _ in states) and not remaining
        reason = "" if verified else ("no_output_from_sources" if not states else
                                      "remaining_defects" if remaining else "not_publishable")
        return {"verified": verified, "basis": BASIS_LEGACY, "reason": reason, "rows_checked": len(states),
                "remaining_defects": remaining, "repair_output_sha256": None, "checked_at": checked_at}

    row, reason = match_target(binding, manifest)
    verdict: dict[str, Any] = {"basis": BASIS_BOUND, "checked_at": checked_at,
                               "original_run_athlete_key": binding.get("run_athlete_key"),
                               "original_output_sha256": request.get("original_output_sha256") or None}
    if row is None:
        return {**verdict, "verified": False, "reason": reason, "remaining_defects": [], "repair_output_sha256": None}
    ok, defects, parts = _row_state(row)
    sha = _primary_sha(row, parts) or None
    original = str(request.get("original_output_sha256") or "").strip()
    remaining = sorted(wanted & defects)
    if not ok:
        reason = "not_publishable"
    elif remaining:
        reason = "remaining_defects"
    elif not sha:
        reason = "repair_output_hash_unknown"
    elif not original:
        reason = "original_output_hash_unknown"
    elif sha == original:
        reason = "output_unchanged"
    else:
        reason = ""
    return {**verdict, "verified": not reason, "reason": reason, "repair_athlete_key": row.get("athlete_key"),
            "publishable": ok, "remaining_defects": remaining, "repair_output_sha256": sha}

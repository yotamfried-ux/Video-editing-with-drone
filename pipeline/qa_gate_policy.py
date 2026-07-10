"""QA gate diagnostics for PQ-009 and REAL-QA-002."""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import os
import sys
from typing import Any

BLOCKING_DEFECT_TYPES = {
    "IDENTITY_MISMATCH",
    "NO_VISIBLE_ACTION",
    "BAD_FRAMING",
    "DUPLICATE_MOMENT",
    "DUPLICATE_DRAFT",
    "QA_REVIEW_REQUIRED",
    "MULTI_PERSON_CLIP",
    "IDENTITY_UNCERTAIN",
    "PREMATURE_CUT",
    "CUT_TOO_EARLY",
}
# These defects are product-blocking even when the LLM labels them "minor".
# The quality report already treats them as hard blocks; the execution gate must
# use the same policy so they cannot bypass re-edit and upload as normal drafts.
ALWAYS_BLOCKING_DEFECT_TYPES = {"PREMATURE_CUT", "CUT_TOO_EARLY"}
_INSTALLED_FLAG = "_sportreel_qa_gate_policy_installed"
_FINDER_FLAG = "_sportreel_qa_gate_import_hook_installed"


def defect_type(defect: dict[str, Any]) -> str:
    return str(defect.get("type", "")).upper()


def is_critical_defect(defect: dict[str, Any]) -> bool:
    dtype = defect_type(defect)
    if dtype in ALWAYS_BLOCKING_DEFECT_TYPES:
        return True
    return str(defect.get("severity", "")).lower() == "critical" and dtype in BLOCKING_DEFECT_TYPES


def critical_defects(qa: dict[str, Any]) -> list[dict[str, Any]]:
    return [defect for defect in qa.get("defects", []) or [] if is_critical_defect(defect)]


def qa_blocking_with_policy(qa: dict[str, Any]) -> bool:
    """Execution gate shared by runtime wiring and deterministic tests."""
    if qa.get("verdict") != "FAIL":
        return False
    return bool(critical_defects(qa))


def normalize_defects_for_repair(defects: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Promote always-blocking cut defects into the existing repair path."""
    normalized: list[dict[str, Any]] = []
    for defect in defects or []:
        item = dict(defect)
        if defect_type(item) in ALWAYS_BLOCKING_DEFECT_TYPES:
            item["severity"] = "critical"
        normalized.append(item)
    return normalized


def review_required_reason_codes(qa: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for defect in critical_defects(qa):
        code = defect_type(defect) or "QA_REVIEW_REQUIRED"
        if code not in codes:
            codes.append(code)
    if qa.get("qa_review_required") and "QA_REVIEW_REQUIRED" not in codes:
        codes.append("QA_REVIEW_REQUIRED")
    return codes


def approval_blocked_reasons(qa: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for defect in critical_defects(qa):
        code = defect_type(defect) or "QA_REVIEW_REQUIRED"
        note = str(defect.get("note", "")).strip()
        reason = f"{code}: {note}" if note else code
        if reason not in reasons:
            reasons.append(reason)
    if qa.get("qa_review_required") and not reasons:
        reasons.append("QA_REVIEW_REQUIRED")
    return reasons


def build_qa_diagnostics(qa: dict[str, Any], *, retry_count: int, decision: str, reel_path: str = "") -> dict[str, Any]:
    defects = []
    for defect in qa.get("defects", []) or []:
        defects.append({
            "type": defect_type(defect),
            "severity": str(defect.get("severity", "")).lower(),
            "at_seconds": defect.get("at_seconds"),
            "event_id": defect.get("event_id") or defect.get("clip_id") or defect.get("source_event_id"),
            "source": defect.get("source") or defect.get("source_video") or defect.get("video"),
            "note": defect.get("note", ""),
            "blocking": is_critical_defect(defect),
            "decision": decision,
        })
    return {
        "decision": decision,
        "final_verdict": qa.get("verdict", "UNKNOWN"),
        "retry_count": int(retry_count),
        "reel_path": os.path.basename(reel_path) if reel_path else "",
        "blocking_defect_types": sorted(BLOCKING_DEFECT_TYPES),
        "always_blocking_defect_types": sorted(ALWAYS_BLOCKING_DEFECT_TYPES),
        "critical_defect_count": len([d for d in defects if d.get("blocking")]),
        "qa_review_required": bool(qa.get("qa_review_required") or decision == "blocked_review_required"),
        "review_required_reasons": review_required_reason_codes(qa),
        "approval_blocked_reasons": approval_blocked_reasons(qa),
        "defects": defects,
        "overall": qa.get("overall", ""),
        "engagement_score": qa.get("engagement_score"),
    }


def build_final_qa_diagnostics(
    qa: dict[str, Any],
    *,
    retry_count: int,
    reel_path: str = "",
    was_flagged: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Classify a final reel and return diagnostics plus review-block state."""
    should_review_block = bool(was_flagged or critical_defects(qa))
    if should_review_block:
        decision = "blocked_review_required"
    elif qa.get("verdict") == "PASS":
        decision = "passed_after_reedit" if retry_count else "passed"
    else:
        decision = "failed_nonblocking"
    return (
        build_qa_diagnostics(
            qa,
            retry_count=retry_count,
            decision=decision,
            reel_path=reel_path,
        ),
        should_review_block,
    )


def visual_family_key(reel_path: str) -> str:
    """Return the shared visual identity for clean and music reel siblings."""
    path = os.path.normcase(os.path.abspath(str(reel_path)))
    root, ext = os.path.splitext(path)
    if root.endswith("_music"):
        root = root[:-6]
    return root + ext.lower()


def retry_count_for_reel(qa_call_counts: dict[str, int], reel_path: str) -> int:
    """Count retries for this visual family only; one QA call is the initial check."""
    return max(0, int(qa_call_counts.get(visual_family_key(reel_path), 0)) - 1)


def attach_qa_diagnostics(events: list[dict[str, Any]], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**event, "qa_gate": diagnostics} for event in events]


def apply_final_qa_to_visual_family(
    final_reels: list[str],
    events_by_reel: dict[str, list[dict[str, Any]]],
    flagged_paths: set[str],
    clean_reel: str,
    qa: dict[str, Any],
    *,
    retry_count: int,
) -> tuple[dict[str, Any], bool]:
    """Attach one visual QA verdict to the clean reel and every music sibling.

    Music variants contain the same visual timeline. A blocking visual defect on
    the clean reel therefore must block every sibling, not only the exact path that
    was sent to the QA model.
    """
    family_key = visual_family_key(clean_reel)
    family = [path for path in final_reels if visual_family_key(path) == family_key]
    if clean_reel not in family:
        family.insert(0, clean_reel)
    was_flagged = any(path in flagged_paths for path in family)
    diagnostics, should_review_block = build_final_qa_diagnostics(
        qa,
        retry_count=retry_count,
        reel_path=clean_reel,
        was_flagged=was_flagged,
    )
    clean_events = events_by_reel.get(clean_reel, [])
    for member in family:
        member_events = events_by_reel.get(member, clean_events)
        events_by_reel[member] = attach_qa_diagnostics(member_events, diagnostics)
        if should_review_block:
            flagged_paths.add(member)
    return diagnostics, should_review_block


def _extract_qa_gate(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events or []:
        qa_gate = event.get("qa_gate")
        if isinstance(qa_gate, dict):
            return qa_gate
    return None


def _augment_metadata_file(meta_file: str, draft_name: str, qa_gate: dict[str, Any]) -> None:
    try:
        with open(meta_file, encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = {}
    entry = metadata.setdefault(draft_name, {})
    entry["qa_gate"] = qa_gate
    entry["qa_review_required"] = bool(qa_gate.get("qa_review_required"))
    entry["review_required"] = bool(qa_gate.get("qa_review_required"))
    entry["approval_blocked_reasons"] = qa_gate.get("approval_blocked_reasons", [])
    if qa_gate.get("qa_review_required"):
        entry["qa_reedit_status"] = "task_created"
    tmp = meta_file + ".qa.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_file)


def _persist_qa_reedit_task(draft_name: str, qa_gate: dict[str, Any]) -> None:
    if not qa_gate.get("qa_review_required"):
        return
    try:
        from integrations.supabase_uploader import upsert_qa_reedit_task
        upsert_qa_reedit_task(draft_name, qa_gate)
    except Exception as exc:
        print(f"  ⚠️  QA re-edit task persistence skipped for {draft_name}: {exc}")


def _patch_orchestrator(orchestrator: Any) -> None:
    import config

    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return

    original_qa_gate = orchestrator._qa_gate
    original_apply_qa_fixes = orchestrator._apply_qa_fixes
    original_save_metadata = orchestrator._save_reel_metadata

    def apply_qa_fixes_with_policy(ordered_events: list[dict], defects: list[dict]):
        return original_apply_qa_fixes(ordered_events, normalize_defects_for_repair(defects))

    orchestrator._qa_blocking = qa_blocking_with_policy
    orchestrator._apply_qa_fixes = apply_qa_fixes_with_policy

    def qa_gate_with_diagnostics(reels, events_out, sport, athlete_label, recompile):
        from pipeline.stages import analyzer
        from pipeline.qa_state import mark_review_required
        original_check = analyzer.qa_check_reel
        qa_by_family: dict[str, dict[str, Any]] = {}
        qa_call_counts: dict[str, int] = {}

        def tracked_qa_check(reel, *args, **kwargs):
            family_key = visual_family_key(reel)
            qa_call_counts[family_key] = qa_call_counts.get(family_key, 0) + 1
            qa = mark_review_required(original_check(reel, *args, **kwargs))
            qa_by_family[family_key] = qa
            return qa

        analyzer.qa_check_reel = tracked_qa_check
        try:
            final, events_by_reel, flagged = original_qa_gate(reels, events_out, sport, athlete_label, recompile)
        finally:
            analyzer.qa_check_reel = original_check

        if not config.QA_REEL_CHECK:
            return final, events_by_reel, flagged

        flagged_set = set(flagged or [])
        final_clean = [r for r in final if "_music" not in os.path.basename(r)]
        for reel in final_clean:
            family_key = visual_family_key(reel)
            qa = qa_by_family.get(family_key)
            if qa is None:
                qa = {
                    "verdict": "FAIL",
                    "defects": [{
                        "type": "QA_REVIEW_REQUIRED",
                        "severity": "critical",
                        "note": "missing final QA details",
                    }],
                    "overall": "missing final QA details",
                    "qa_review_required": True,
                    "engagement_score": 0,
                }
                flagged_set.add(reel)

            apply_final_qa_to_visual_family(
                final,
                events_by_reel,
                flagged_set,
                reel,
                qa,
                retry_count=retry_count_for_reel(qa_call_counts, reel),
            )
        return final, events_by_reel, flagged_set

    def save_metadata_with_qa(draft_name, sport, events, source_quality):
        original_save_metadata(draft_name, sport, events, source_quality)
        qa_gate = _extract_qa_gate(events)
        if qa_gate:
            _augment_metadata_file(config.REEL_METADATA_FILE, draft_name, qa_gate)
            _persist_qa_reedit_task(draft_name, qa_gate)

    orchestrator._qa_gate = qa_gate_with_diagnostics
    orchestrator._save_reel_metadata = save_metadata_with_qa
    setattr(orchestrator, _INSTALLED_FLAG, True)


class _OrchestratorPatchLoader(importlib.abc.Loader):
    def __init__(self, loader: importlib.abc.Loader):
        self.loader = loader

    def create_module(self, spec):
        create = getattr(self.loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module) -> None:
        self.loader.exec_module(module)
        _patch_orchestrator(module)


class _OrchestratorPatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "pipeline.orchestrator":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _OrchestratorPatchLoader(spec.loader)
        return spec


def install() -> None:
    existing = sys.modules.get("pipeline.orchestrator")
    if existing is not None:
        _patch_orchestrator(existing)
        return
    if not any(getattr(finder, _FINDER_FLAG, False) for finder in sys.meta_path):
        finder = _OrchestratorPatchFinder()
        setattr(finder, _FINDER_FLAG, True)
        sys.meta_path.insert(0, finder)

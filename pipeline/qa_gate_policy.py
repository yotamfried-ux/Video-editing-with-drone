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


def attach_qa_diagnostics(events: list[dict[str, Any]], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**event, "qa_gate": diagnostics} for event in events]


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

    def qa_blocking_with_policy(qa: dict[str, Any]) -> bool:
        if qa.get("verdict") != "FAIL":
            return False
        return bool(critical_defects(qa))

    def apply_qa_fixes_with_policy(ordered_events: list[dict], defects: list[dict]):
        # orchestrator._apply_qa_fixes historically ignored every non-critical
        # defect before reaching the PREMATURE_CUT handler. Normalize defects that
        # are always blocking so the existing +3s repair path actually runs.
        normalized: list[dict] = []
        for defect in defects or []:
            item = dict(defect)
            if defect_type(item) in ALWAYS_BLOCKING_DEFECT_TYPES:
                item["severity"] = "critical"
            normalized.append(item)
        return original_apply_qa_fixes(ordered_events, normalized)

    # original_qa_gate resolves these names from the orchestrator module at call
    # time, so replacing the module globals aligns execution with report policy.
    orchestrator._qa_blocking = qa_blocking_with_policy
    orchestrator._apply_qa_fixes = apply_qa_fixes_with_policy

    def qa_gate_with_diagnostics(reels, events_out, sport, athlete_label, recompile):
        from pipeline.stages import analyzer
        from pipeline.qa_state import mark_review_required
        original_check = analyzer.qa_check_reel
        qa_by_reel: dict[str, dict[str, Any]] = {}
        call_count = 0

        def tracked_qa_check(reel, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            qa = mark_review_required(original_check(reel, *args, **kwargs))
            qa_by_reel[reel] = qa
            return qa

        analyzer.qa_check_reel = tracked_qa_check
        try:
            final, events_by_reel, flagged = original_qa_gate(reels, events_out, sport, athlete_label, recompile)
        finally:
            analyzer.qa_check_reel = original_check

        if not config.QA_REEL_CHECK:
            return final, events_by_reel, flagged

        initial_clean_count = len([r for r in reels if "_music" not in os.path.basename(r)])
        retry_count = max(0, call_count - initial_clean_count)
        flagged_set = set(flagged or [])
        final_clean = [r for r in final if "_music" not in os.path.basename(r)]
        for reel in final_clean:
            qa = qa_by_reel.get(reel)
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

            blocking = bool(critical_defects(qa))
            if blocking:
                flagged_set.add(reel)

            if reel in flagged_set:
                decision = "blocked_review_required"
            elif qa.get("verdict") == "PASS":
                decision = "passed_after_reedit" if retry_count else "passed"
            else:
                # Technical or engagement-only FAILs remain visible in telemetry
                # but do not masquerade as content defects requiring re-edit.
                decision = "failed_nonblocking"

            diagnostics = build_qa_diagnostics(
                qa,
                retry_count=retry_count,
                decision=decision,
                reel_path=reel,
            )
            events_by_reel[reel] = attach_qa_diagnostics(events_by_reel.get(reel, []), diagnostics)
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

"""Inject edit/source context into reel QA calls."""
from __future__ import annotations

import json
import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_source_context_qa_installed"


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _src(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def build_edit_context(reel_path: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    windows = []
    for idx, event in enumerate(events or []):
        if event.get("_teaser"):
            continue
        windows.append({
            "event_id": _event_id(event, idx),
            "source": _src(event),
            "source_start": event.get("start"),
            "source_end": event.get("end"),
            "final_cut_start": event.get("final_cut_start"),
            "final_cut_end": event.get("final_cut_end"),
            "track_id": event.get("track_id"),
            "identity_gate": event.get("identity_gate"),
            "cut_window_guard": {
                "status": event.get("cut_window_evidence_status"),
                "reason": event.get("cut_window_guard_reason"),
                "original_end_before_guard": event.get("original_end_before_cut_guard"),
                "window_uncertain": event.get("window_uncertain"),
            } if event.get("cut_window_evidence_status") else None,
            "duplicate_evidence": event.get("dedup_dropped_duplicates", []),
        })
    return {"reel": reel_path, "source_windows": windows}


def context_prompt(context: dict[str, Any]) -> str:
    compact = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return (
        "\nEDIT_SOURCE_CONTEXT_JSON:\n"
        f"{compact}\n"
        "Use this edit JSON to judge the final draft against its source windows. "
        "Check whether the same athlete is preserved, whether any wave/action is cut before its outcome, "
        "and whether selected moments duplicate another source window."
    )


def wrap_qa_check(original, context_by_reel: dict[str, dict[str, Any]]):
    def wrapped(reel, *args, **kwargs):
        ctx = context_by_reel.get(reel)
        if ctx:
            label = str(kwargs.get("athlete_label", ""))
            kwargs["athlete_label"] = label + context_prompt(ctx)
        return original(reel, *args, **kwargs)
    return wrapped


def _patch_orchestrator(orchestrator: Any) -> None:
    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return
    original_gate = orchestrator._qa_gate

    def qa_gate_with_source_context(reels, events_out, sport, athlete_label, recompile):
        from pipeline.stages import analyzer
        context_by_reel = {reel: build_edit_context(reel, events) for reel, events in events_out}
        original_check = analyzer.qa_check_reel
        analyzer.qa_check_reel = wrap_qa_check(original_check, context_by_reel)
        try:
            return original_gate(reels, events_out, sport, athlete_label, recompile)
        finally:
            analyzer.qa_check_reel = original_check

    orchestrator._qa_gate = qa_gate_with_source_context
    setattr(orchestrator, _INSTALLED_FLAG, True)


def install() -> None:
    module = sys.modules.get("pipeline.orchestrator")
    if module is not None:
        _patch_orchestrator(module)

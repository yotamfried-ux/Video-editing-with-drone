"""Patch context QA to require source-window evidence review."""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED = "_sportreel_source_evidence_patch_installed"


def install() -> None:
    import pipeline.context_qa_gate as gate
    if getattr(gate, _INSTALLED, False):
        return

    def qa_gate_with_source_evidence(orchestrator: Any, reels, events_out, sport, athlete_label, recompile):
        from pipeline.stages import analyzer
        from pipeline.source_evidence_runner import with_source_evidence
        context_by_reel = {reel: gate.build_edit_context(reel, events) for reel, events in events_out}
        original_check = analyzer.qa_check_reel
        def contextual_check(reel, *args, **kwargs):
            ctx = context_by_reel.get(reel)
            if ctx:
                kwargs["athlete_label"] = str(kwargs.get("athlete_label", "")) + gate._context_prompt(ctx)
                return with_source_evidence(analyzer, original_check, reel, *args, context=ctx, **kwargs)
            return original_check(reel, *args, **kwargs)
        analyzer.qa_check_reel = contextual_check
        try:
            return orchestrator._qa_gate(reels, events_out, sport, athlete_label, recompile)
        finally:
            analyzer.qa_check_reel = original_check

    gate._qa_gate_with_edit_context = qa_gate_with_source_evidence
    setattr(gate, _INSTALLED, True)

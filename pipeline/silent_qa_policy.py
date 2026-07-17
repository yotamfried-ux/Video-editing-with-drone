"""Make deterministic final QA validate silence instead of requiring audio."""
from __future__ import annotations

from typing import Any

_INSTALLED_FLAG = "_sportreel_silent_qa_policy_installed"


def install() -> None:
    """Replace the historical audio-required QA check with silent-output QA."""
    from pipeline.stages import analyzer

    if getattr(analyzer, _INSTALLED_FLAG, False):
        return
    original = analyzer._check_technical_compliance

    def check_silent_technical_compliance(reel_path: str) -> tuple[dict, bool, list[str]]:
        specs, _passed, original_issues = original(reel_path)
        issues = [
            str(issue)
            for issue in original_issues
            if str(issue).strip().lower() != "no audio track"
        ]
        audio_state: Any = specs.get("has_audio")
        if audio_state is True:
            issues.append("unexpected audio track")
        elif audio_state is not False:
            issues.append("audio stream state could not prove silence")
        return specs, not issues, issues

    analyzer._check_technical_compliance = check_silent_technical_compliance
    setattr(analyzer, _INSTALLED_FLAG, True)
